"""Immutable payment collection records; no external bank transaction occurs."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from norin_delivery.models import DeliveryQuote, DomainError, money, new_id, required


class PaymentComparison(str, Enum):
    """Outcome of comparing one recorded collection with accepted quote terms."""

    MATCH = "Match"
    MISMATCH = "Mismatch"


@dataclass(frozen=True)
class Payment:
    """An append-only record of one reported collection for an accepted delivery.

    This class records a collection and its comparison outcome. It does not
    contact a bank, alter an accepted quote, or decide partial-payment policy.
    """

    payment_id: str
    delivery_id: str
    quote_id: str
    amount_received: Decimal
    accepted_amount: Decimal
    collected_at: datetime

    def __post_init__(self) -> None:
        required(self.payment_id, "Payment ID")
        required(self.delivery_id, "Delivery ID")
        required(self.quote_id, "Quote ID")
        object.__setattr__(self, "amount_received", money(self.amount_received))
        object.__setattr__(self, "accepted_amount", money(self.accepted_amount))
        if not isinstance(self.collected_at, datetime):
            raise DomainError("Collection time must be a datetime value.")
        if self.collected_at.tzinfo is None or self.collected_at.utcoffset() is None:
            raise DomainError("Collection time must include a timezone.")

    @classmethod
    def record_collection(
        cls,
        delivery_id: str,
        accepted_quote: DeliveryQuote,
        amount_received: str | Decimal,
        collected_at: datetime | None = None,
    ) -> "Payment":
        """Record an amount against a delivery created from an accepted quote."""
        delivery_id = required(delivery_id, "Delivery ID")
        accepted_amount, _, _ = accepted_quote.get_accepted_terms()
        if not accepted_quote.delivery_id or accepted_quote.delivery_id != delivery_id:
            raise DomainError("Delivery does not match the accepted quote.")
        timestamp = collected_at or datetime.now(timezone.utc)
        return cls(
            payment_id=new_id("PAY"),
            delivery_id=delivery_id,
            quote_id=accepted_quote.quote_id,
            amount_received=money(amount_received),
            accepted_amount=money(accepted_amount),
            collected_at=timestamp,
        )

    @property
    def comparison_result(self) -> PaymentComparison:
        """Return whether this collection equals the snapshotted accepted amount."""
        if self.amount_received == self.accepted_amount:
            return PaymentComparison.MATCH
        return PaymentComparison.MISMATCH
