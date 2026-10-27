"""The boundary where Mekno's delivery implementation connects."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from .models import DeliveryQuote, DeliveryRequest, DomainError, QuoteDecision


@dataclass(frozen=True)
class AcceptedDeliveryData:
    quote_id: str
    request_id: str
    customer_id: str
    pickup_address: str
    destination_address: str
    parcels: tuple[tuple[str, str], ...]
    amount: Decimal
    estimated_pickup: datetime
    estimated_delivery: datetime
    decision_recorded_by: str
    decision_at: str

    @classmethod
    def from_quote(cls, quote: DeliveryQuote,
                   request: DeliveryRequest) -> "AcceptedDeliveryData":
        if quote.decision != QuoteDecision.ACCEPTED:
            raise DomainError("Only accepted quotes may be handed to delivery.")
        return cls(
            quote.quote_id, request.request_id, request.customer_id,
            request.pickup_address, request.destination_address,
            tuple((p.parcel_id, p.description) for p in request.parcels),
            *quote.get_accepted_terms(),
            quote.decision_recorded_by, quote.decision_at,
        )


class DeliveryGateway(Protocol):
    def create_or_get_delivery(self, data: AcceptedDeliveryData) -> str:
        """Persist one Delivery per quote_id and return its stable ID.

        Must be idempotent across restarts, including retries after a local
        save failure. Raise an exception if creation cannot be completed.
        """
        ...


class DemoDeliveryGateway:
    """Placeholder ONLY: no staff, payment or actual Delivery is implemented."""

    def create_or_get_delivery(self, data: AcceptedDeliveryData) -> str:
        return f"DEMO-DEL-{data.quote_id}"
