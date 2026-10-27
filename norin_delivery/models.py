"""Business objects and rules, independent of the console and file storage.

Records are immutable: editing operations return a replacement object.
The application saves related replacements together in one transaction.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from uuid import uuid4


class DomainError(ValueError):
    """A validation or business-rule failure suitable for display."""


class Role(str, Enum):
    CUSTOMER = "Customer"
    OFFICE = "Office staff"
    MANAGER = "Manager"
    DELIVERY = "Delivery staff"


class RequestState(str, Enum):
    DRAFT = "Draft"
    SUBMITTED = "Submitted"
    QUOTED = "Quoted"
    ACCEPTED = "Accepted"
    REJECTED = "Rejected"


class QuoteDecision(str, Enum):
    PENDING = "Pending"
    ACCEPTED = "Accepted"
    REJECTED = "Rejected"


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def required(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise DomainError(f"{label} must not be blank.")
    return value


def now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def money(value: str | Decimal) -> Decimal:
    try:
        amount = Decimal(value)
        if not amount.is_finite() or not 0 < amount <= Decimal("999999.99"):
            raise DomainError("Cost must be between AUD 0.01 and 999999.99.")
        if amount != amount.quantize(Decimal("0.01")):
            raise DomainError("Cost must have no more than two decimal places.")
        return amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        if isinstance(exc, DomainError):
            raise
        raise DomainError("Enter a valid cost, for example 45.50.") from exc


def local_time(value: str) -> datetime:
    """Parse a Melbourne wall-clock estimate; no UTC conversion is implied."""
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", value):
            raise ValueError
        return datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise DomainError("Use YYYY-MM-DD HH:MM, in Melbourne local time.") from exc


@dataclass(frozen=True)
class Customer:
    customer_id: str
    display_name: str
    phone: str = ""
    email: str = ""

    def __post_init__(self) -> None:
        required(self.display_name, "Customer name")
        if not self.phone.strip() and not self.email.strip():
            raise DomainError("Provide a phone number or an email address.")
        if self.email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", self.email):
            raise DomainError("Enter a valid email address.")
        if self.phone:
            digits = re.sub(r"\D", "", self.phone)
            if not re.fullmatch(r"[+\d ()-]+", self.phone) or not 8 <= len(digits) <= 15:
                raise DomainError("Phone must contain 8 to 15 digits.")

    def update_contact_details(self, name: str, phone: str, email: str) -> Customer:
        return replace(self, display_name=name.strip(), phone=phone.strip(),
                       email=email.strip())

    def create_request(self, pickup: str, destination: str) -> DeliveryRequest:
        return DeliveryRequest(new_id("REQ"), self.customer_id,
                               pickup.strip(), destination.strip())

    def get_requests(self, requests: list[DeliveryRequest]) -> list[DeliveryRequest]:
        return [item for item in requests if item.customer_id == self.customer_id]


@dataclass(frozen=True)
class UserAccount:
    account_id: str
    username: str
    credential_hash: str
    role: Role
    active: bool = True
    customer_id: str | None = None
    staff_id: str | None = None

    @classmethod
    def register(cls, username: str, password: str, role: Role,
                 customer_id: str | None = None,
                 staff_id: str | None = None) -> UserAccount:
        """Construct an account; the service checks uniqueness and authority."""
        username = username.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username):
            raise DomainError("Username: 3-40 letters, digits, dots, _ or -.")
        if len(password) < 8 or not password.strip():
            raise DomainError("Password must contain at least 8 characters.")
        if role == Role.CUSTOMER and not customer_id:
            raise DomainError("Customer account requires a customer record.")
        if staff_id is not None:
            staff_id = staff_id.strip()
        if role == Role.DELIVERY and not staff_id:
            raise DomainError("Delivery staff account requires a staff ID.")
        salt = secrets.token_hex(16)
        rounds = 600_000
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), rounds,
        ).hex()
        encoded = f"pbkdf2_sha256${rounds}${salt}${digest}"
        return cls(new_id("ACC"), username, encoded, role,
                   customer_id=customer_id, staff_id=staff_id)

    def verify_password(self, password: str) -> bool:
        algorithm, rounds, salt, expected = self.credential_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(rounds),
        ).hex()
        return hmac.compare_digest(actual, expected)

    def can_submit_request(self, customer_id: str) -> bool:
        return self.active and (
            self.role in (Role.OFFICE, Role.MANAGER)
            or (self.role == Role.CUSTOMER and self.customer_id == customer_id)
        )

    def can_record_quote_decision(self, customer_id: str) -> bool:
        return self.can_submit_request(customer_id)

    def require_office(self) -> None:
        if not self.active or self.role not in (Role.OFFICE, Role.MANAGER):
            raise DomainError("An active office-staff or manager account is required.")

    def deactivate(self) -> UserAccount:
        return replace(self, active=False)


@dataclass(frozen=True)
class Parcel:
    parcel_id: str
    description: str

    def __post_init__(self) -> None:
        required(self.description, "Parcel description")

    def update_description(self, description: str) -> Parcel:
        """The owning request checks editability before calling this method."""
        return replace(self, description=description.strip())

    def get_details(self) -> str:
        return f"{self.parcel_id}: {self.description}"


@dataclass(frozen=True)
class DeliveryRequest:
    request_id: str
    customer_id: str
    pickup_address: str
    destination_address: str
    parcels: tuple[Parcel, ...] = ()
    state: RequestState = RequestState.DRAFT
    quote_id: str | None = None

    def require_draft(self) -> None:
        if self.state != RequestState.DRAFT:
            raise DomainError("Only draft requests can be edited.")

    def add_parcel(self, description: str) -> DeliveryRequest:
        self.require_draft()
        parcel = Parcel(new_id("PAR"), description.strip())
        return replace(self, parcels=self.parcels + (parcel,))

    def remove_parcel(self, parcel_id: str) -> DeliveryRequest:
        self.require_draft()
        self.find_parcel(parcel_id)
        return replace(self, parcels=tuple(
            p for p in self.parcels if p.parcel_id != parcel_id
        ))

    def find_parcel(self, parcel_id: str) -> Parcel:
        for parcel in self.parcels:
            if parcel.parcel_id == parcel_id:
                return parcel
        raise DomainError("Parcel was not found in this request.")

    def update_parcel(self, parcel_id: str, description: str) -> DeliveryRequest:
        self.require_draft()
        edited = self.find_parcel(parcel_id).update_description(description)
        return replace(self, parcels=tuple(
            edited if p.parcel_id == parcel_id else p for p in self.parcels
        ))

    def update_locations(self, pickup: str, destination: str) -> DeliveryRequest:
        self.require_draft()
        return replace(self, pickup_address=pickup.strip(),
                       destination_address=destination.strip())

    def validate_for_quote(self) -> list[str]:
        errors = []
        if not self.pickup_address:
            errors.append("Pickup address is required.")
        if not self.destination_address:
            errors.append("Destination address is required.")
        if not self.parcels:
            errors.append("At least one described parcel is required.")
        return errors

    def submit(self) -> DeliveryRequest:
        self.require_draft()
        errors = self.validate_for_quote()
        if errors:
            raise DomainError(" ".join(errors))
        return replace(self, state=RequestState.SUBMITTED)

    def create_quote(self, cost: str, pickup_time: str, delivery_time: str,
                     actor: UserAccount) -> DeliveryQuote:
        actor.require_office()
        if self.quote_id:
            raise DomainError("This request already has a quote.")
        if self.state != RequestState.SUBMITTED:
            raise DomainError("The customer must submit the request before quotation.")
        errors = self.validate_for_quote()
        if errors:
            raise DomainError(" ".join(errors))
        return DeliveryQuote(
            new_id("QUO"), self.request_id, money(cost),
            local_time(pickup_time), local_time(delivery_time),
            actor.account_id, now_text(),
        )


@dataclass(frozen=True)
class DeliveryQuote:
    quote_id: str
    request_id: str
    quoted_cost: Decimal
    estimated_pickup: datetime
    estimated_delivery: datetime
    prepared_by: str
    prepared_at: str
    decision: QuoteDecision = QuoteDecision.PENDING
    decision_at: str | None = None
    decision_recorded_by: str | None = None
    delivery_id: str | None = None

    def __post_init__(self) -> None:
        money(self.quoted_cost)
        if self.estimated_delivery <= self.estimated_pickup:
            raise DomainError("Estimated delivery must be after pickup.")

    def _authorise(self, actor: UserAccount, customer_id: str) -> None:
        if not actor.can_record_quote_decision(customer_id):
            raise DomainError("You cannot decide on this customer's quote.")

    def accept(self, actor: UserAccount, customer_id: str) -> DeliveryQuote:
        """Return accepted terms; the service then completes the handoff."""
        self._authorise(actor, customer_id)
        if self.decision == QuoteDecision.REJECTED:
            raise DomainError("A rejected quote cannot be accepted.")
        if self.decision == QuoteDecision.ACCEPTED:
            return self
        return replace(self, decision=QuoteDecision.ACCEPTED,
                       decision_at=now_text(),
                       decision_recorded_by=actor.account_id)

    def reject(self, actor: UserAccount, customer_id: str) -> DeliveryQuote:
        self._authorise(actor, customer_id)
        if self.decision == QuoteDecision.ACCEPTED:
            raise DomainError("An accepted quote cannot be rejected.")
        if self.decision == QuoteDecision.REJECTED:
            return self
        return replace(self, decision=QuoteDecision.REJECTED,
                       decision_at=now_text(),
                       decision_recorded_by=actor.account_id)

    def get_accepted_terms(self) -> tuple[Decimal, datetime, datetime]:
        if self.decision != QuoteDecision.ACCEPTED:
            raise DomainError("Quote has not been accepted.")
        return (self.quoted_cost, self.estimated_pickup,
                self.estimated_delivery)
