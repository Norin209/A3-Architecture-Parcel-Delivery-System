# Connecting Norin's module to the group system

## Boundary for Mekno

Implement `DeliveryGateway.create_or_get_delivery(data)` and pass your adapter
to `DeliveryApplication`. This method receives an immutable
`AcceptedDeliveryData` containing:

- Quote/request/customer IDs and both addresses.
- Parcel `(id, description)` pairs.
- Accepted `Decimal` amount and pickup/delivery datetime estimates.
- The deciding account ID and the UTC decision timestamp.

The method must persist the actual `Delivery` and return its stable string ID.
Use **quote_id as the unique idempotency key**: every retry for the same quote,
including after a restart, must return the same Delivery. Reject inconsistent
terms for an already known quote. Populate the delivery and its initial status
record as your module requires; no allocation occurs in Norin's module.

```python
from norin_delivery.service import DeliveryApplication
from norin_delivery.storage import JsonRepository

# Implement this adapter using Mekno's actual repository and Delivery API.
# This is the integration contract, not a claim about existing teammate code.
class MeknoGateway:
    def __init__(self, delivery_service):
        self.delivery_service = delivery_service

    def create_or_get_delivery(self, data):
        return self.delivery_service.create_or_get_by_quote(data)

app = DeliveryApplication(
    JsonRepository("data/integrated.json"),
    MeknoGateway(delivery_service),  # Provided by the group bootstrap.
)
```

The real group console can call `app.login`, `create_request`, `edit_request`,
`create_quote`, and `decide_quote`, or use the same application from another UI.
Do not edit the repository dictionaries directly. A service instance owns one
signed-in session. All user operations go through the service so ownership,
active-account and role checks run.

### Failure semantics

1. Validate authority and quote state before invoking the adapter.
2. Invoke the adapter with accepted terms. If it raises, no local decision is
   saved and the operation reports a failed handoff.
3. Save the delivery ID, accepted quote and request state in one JSON replace.
4. Repeated acceptance of a locally accepted quote returns the stored record
   without invoking the adapter again.

There is **no distributed transaction** across the group's independent stores.
If the external delivery is saved but the local save fails, the local quote
remains pending. Retry acceptance after storage recovery; the idempotent
adapter must return the existing delivery. If no retry occurs, the group needs
a reconciliation step. For a stronger final design, use one shared transaction
or a durable outbox/reconciliation process. Do not claim cross-store atomicity
in the report. Tests exercise this failure and retry explicitly.

`DemoDeliveryGateway` is only a deterministic placeholder. Its IDs start with
`DEMO-DEL-`. Start integrated testing with a fresh JSON file to avoid treating
previous demo acceptances as real deliveries.

## Accounts and staff records

The initial manager can create office, manager and delivery-staff accounts.
For delivery staff, Mekno's workflow must create/identify a real `DeliveryStaff`
record and pass its ID into `register_staff_account`. The standalone module
requires a nonblank ID but cannot verify a record in an unconnected module.
Coordinate rollback if staff creation succeeds but account creation fails.

## Boundary for Tola

Payment and status operations begin on the actual Delivery returned by Mekno's
adapter. The handoff includes accepted terms for payment checking and audit
information for the initial status. Norin's module does not create Tola's
payment/status records.

The standalone payment-domain model is `tola_payment.Payment`:

```python
from tola_payment import Payment

payment = Payment.record_collection(
    delivery_id=delivery_id,  # The stable ID returned by Mekno's Delivery module.
    accepted_quote=accepted_quote,  # The accepted quote retained by the integration.
    amount_received="45.50",
)
if payment.comparison_result.value == "Mismatch":
    # Keep the recorded mismatch visible for operational follow-up.
    ...
```

`accepted_quote` must be accepted and its delivery ID must match the supplied
delivery. The immutable record keeps the received amount, accepted amount,
quote/delivery IDs and timezone-aware collection time; the comparison is
derived from those values. This is a domain record only: the caller must retain
it. It does not yet add persistence, a UI workflow, bank processing, partial-
payment rules or duplicate-entry protection. Those decisions and the actual
Delivery API must be agreed before end-to-end integration.

The shared initializer should construct repositories/adapters before enabling
normal menus. No external payment service is required by A3.

## Report reconciliation

Update the final shared class diagram with the implemented field types and
methods. Add `DeliveryApplication`, `JsonRepository`, `Records`, `Console`,
`DeliveryGateway` and `AcceptedDeliveryData` as technical collaborators.
`DemoDeliveryGateway` is test/demo scaffolding, not a production domain class.

Relevant changes from the draft report: snake_case, immutable replacement
records, ID-based relationships, decision orchestration in the application,
and explicit integration failure/retry semantics. Keep initial design claims
separate from observations about actual implementation and testing.
