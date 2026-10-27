"""Versioned JSON storage with atomic replacement and validation."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .models import (
    Customer, DeliveryQuote, DeliveryRequest, DomainError, Parcel,
    QuoteDecision, RequestState, Role, UserAccount,
)


class StorageError(RuntimeError):
    """Storage failed; the original file must not be silently discarded."""


@dataclass
class Records:
    customers: dict[str, Customer] = field(default_factory=dict)
    accounts: dict[str, UserAccount] = field(default_factory=dict)
    requests: dict[str, DeliveryRequest] = field(default_factory=dict)
    quotes: dict[str, DeliveryQuote] = field(default_factory=dict)

    def validate(self) -> None:
        usernames = set()
        linked_customers = set()
        for account in self.accounts.values():
            username = account.username.casefold()
            if username in usernames:
                raise ValueError("Duplicate username")
            usernames.add(username)
            if account.role == Role.CUSTOMER:
                if account.customer_id not in self.customers:
                    raise ValueError("Missing account/customer link")
                if account.customer_id in linked_customers:
                    raise ValueError("Customer has multiple accounts")
                linked_customers.add(account.customer_id)
            if account.role == Role.DELIVERY and not account.staff_id:
                raise ValueError("Missing staff link")
            algorithm, rounds, salt, digest = account.credential_hash.split("$")
            if algorithm != "pbkdf2_sha256" or not 100_000 <= int(rounds) <= 2_000_000:
                raise ValueError("Invalid password hash format")
            if len(bytes.fromhex(salt)) != 16 or len(bytes.fromhex(digest)) != 32:
                raise ValueError("Invalid password hash length")
            if not isinstance(account.active, bool):
                raise ValueError("Invalid account activity flag")
        parcel_ids = set()
        for request in self.requests.values():
            if request.customer_id not in self.customers:
                raise ValueError("Missing request/customer link")
            for parcel in request.parcels:
                if parcel.parcel_id in parcel_ids:
                    raise ValueError("Parcel belongs to more than one request")
                parcel_ids.add(parcel.parcel_id)
            if request.state == RequestState.DRAFT:
                if request.quote_id:
                    raise ValueError("Draft has a quote")
            else:
                quote = self.quotes.get(request.quote_id)
                if not quote or quote.request_id != request.request_id:
                    raise ValueError("Missing request/quote link")
                if request.validate_for_quote():
                    raise ValueError("Quoted request is incomplete")
                expected = {
                    QuoteDecision.PENDING: RequestState.QUOTED,
                    QuoteDecision.ACCEPTED: RequestState.ACCEPTED,
                    QuoteDecision.REJECTED: RequestState.REJECTED,
                }[quote.decision]
                if request.state != expected:
                    raise ValueError("Request and quote states disagree")
        for quote in self.quotes.values():
            request = self.requests.get(quote.request_id)
            if not request or request.quote_id != quote.quote_id:
                raise ValueError("Missing quote/request link")
            if quote.prepared_by not in self.accounts:
                raise ValueError("Missing quote author")
            if quote.decision == QuoteDecision.PENDING:
                if quote.decision_at or quote.decision_recorded_by or quote.delivery_id:
                    raise ValueError("Pending quote has decision data")
            else:
                if not quote.decision_at or quote.decision_recorded_by not in self.accounts:
                    raise ValueError("Missing quote decision audit data")
                if (quote.decision == QuoteDecision.ACCEPTED) != bool(quote.delivery_id):
                    raise ValueError("Invalid quote/delivery link")


class JsonRepository:
    """Single-process repository; keep only one console open per data file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.records = self._load()

    def _load(self) -> Records:
        if not self.path.exists():
            return Records()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data["schema_version"] != 1:
                raise ValueError("Unsupported schema version")
            result = Records()
            for item in data["customers"]:
                self._insert(result.customers, Customer(**item), "customer_id")
            for item in data["accounts"]:
                item["role"] = Role(item["role"])
                self._insert(result.accounts, UserAccount(**item), "account_id")
            for item in data["requests"]:
                item["parcels"] = tuple(Parcel(**p) for p in item["parcels"])
                item["state"] = RequestState(item["state"])
                self._insert(result.requests, DeliveryRequest(**item), "request_id")
            for item in data["quotes"]:
                item["quoted_cost"] = Decimal(item["quoted_cost"])
                item["estimated_pickup"] = datetime.fromisoformat(item["estimated_pickup"])
                item["estimated_delivery"] = datetime.fromisoformat(item["estimated_delivery"])
                item["decision"] = QuoteDecision(item["decision"])
                self._insert(result.quotes, DeliveryQuote(**item), "quote_id")
            result.validate()
            return result
        except (OSError, ValueError, KeyError, TypeError, AttributeError,
                InvalidOperation) as exc:
            raise StorageError(
                f"Cannot load {self.path}: {exc}. Original file was not changed."
            ) from exc

    @staticmethod
    def _insert(collection: dict, record: object, key: str) -> None:
        identifier = getattr(record, key)
        if not isinstance(identifier, str) or not identifier or identifier in collection:
            raise ValueError("Invalid or duplicate record ID")
        collection[identifier] = record

    @staticmethod
    def _encode(value: object) -> str:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError(f"Unsupported saved type: {type(value).__name__}")

    def commit(self, records: Records) -> None:
        """Write first, then publish state; failed writes leave memory intact."""
        temp_path = None
        try:
            records.validate()
            payload = {
                "schema_version": 1,
                "customers": [asdict(x) for x in records.customers.values()],
                "accounts": [asdict(x) for x in records.accounts.values()],
                "requests": [asdict(x) for x in records.requests.values()],
                "quotes": [asdict(x) for x in records.quotes.values()],
            }
            text = json.dumps(payload, default=self._encode, indent=2)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=self.path.name + ".", suffix=".tmp", delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(text + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            self.records = records
        except (OSError, ValueError, TypeError) as exc:
            raise StorageError(f"Save failed; changes were not committed: {exc}") from exc
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    # A failed cleanup must not hide the original save error.
                    pass
