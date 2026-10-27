"""Use cases joining business rules, persistence and the delivery handoff."""

from copy import deepcopy
from dataclasses import replace

from .integration import AcceptedDeliveryData, DeliveryGateway
from .models import (
    Customer, DeliveryQuote, DeliveryRequest, DomainError, QuoteDecision,
    RequestState, Role, UserAccount, new_id,
)
from .storage import JsonRepository


class DeliveryApplication:
    def __init__(self, repository: JsonRepository, gateway: DeliveryGateway):
        self.repository = repository
        self.gateway = gateway
        self._account_id: str | None = None

    @property
    def needs_setup(self) -> bool:
        return not self.repository.records.accounts

    @property
    def signed_in(self) -> bool:
        return self._account_id is not None

    def _unique_username(self, username: str) -> None:
        if any(a.username.casefold() == username.strip().casefold()
               for a in self.repository.records.accounts.values()):
            raise DomainError("That username already exists.")

    def setup_manager(self, username: str, password: str) -> UserAccount:
        if not self.needs_setup:
            raise DomainError("Initial manager has already been created.")
        account = UserAccount.register(username, password, Role.MANAGER)
        records = deepcopy(self.repository.records)
        records.accounts[account.account_id] = account
        self.repository.commit(records)
        return account

    def login(self, username: str, password: str) -> UserAccount:
        self.logout()
        for account in self.repository.records.accounts.values():
            if (account.username.casefold() == username.strip().casefold()
                    and account.active and account.verify_password(password)):
                self._account_id = account.account_id
                return account
        raise DomainError("Invalid username/password or inactive account.")

    def logout(self) -> None:
        self._account_id = None

    @property
    def actor(self) -> UserAccount:
        account = self.repository.records.accounts.get(self._account_id)
        if account is None or not account.active:
            raise DomainError("Sign in with an active account first.")
        return account

    def register_customer(self, name: str, phone: str, email: str,
                          username: str, password: str) -> Customer:
        if self.needs_setup:
            raise DomainError("Create the initial manager first.")
        self._unique_username(username)
        customer = Customer(new_id("CUS"), name.strip(), phone.strip(), email.strip())
        account = UserAccount.register(username, password, Role.CUSTOMER,
                                       customer_id=customer.customer_id)
        records = deepcopy(self.repository.records)
        records.customers[customer.customer_id] = customer
        records.accounts[account.account_id] = account
        self.repository.commit(records)
        return customer

    def create_phone_customer(self, name: str, phone: str, email: str) -> Customer:
        self.actor.require_office()
        customer = Customer(new_id("CUS"), name.strip(), phone.strip(), email.strip())
        records = deepcopy(self.repository.records)
        records.customers[customer.customer_id] = customer
        self.repository.commit(records)
        return customer

    def register_staff_account(self, username: str, password: str,
                               role: Role, staff_id: str | None = None) -> UserAccount:
        if self.actor.role != Role.MANAGER:
            raise DomainError("Only a manager can register staff accounts.")
        if role not in (Role.MANAGER, Role.OFFICE, Role.DELIVERY):
            raise DomainError("Choose a staff role.")
        self._unique_username(username)
        if role == Role.DELIVERY and hasattr(self.gateway, 'validate_staff'):
            self.gateway.validate_staff(staff_id)
        account = UserAccount.register(username, password, role, staff_id=staff_id)
        records = deepcopy(self.repository.records)
        records.accounts[account.account_id] = account
        self.repository.commit(records)
        return account

    def list_accounts(self) -> list[UserAccount]:
        if self.actor.role != Role.MANAGER:
            raise DomainError("Only a manager can list accounts.")
        return list(self.repository.records.accounts.values())

    def deactivate_account(self, account_id: str) -> None:
        actor = self.actor
        if actor.role != Role.MANAGER:
            raise DomainError("Only a manager can deactivate accounts.")
        if actor.account_id == account_id:
            raise DomainError("Use another manager to deactivate your own account.")
        records = deepcopy(self.repository.records)
        target = records.accounts.get(account_id)
        if target is None:
            raise DomainError("Account not found.")
        records.accounts[account_id] = target.deactivate()
        self.repository.commit(records)

    def list_customers(self) -> list[Customer]:
        actor = self.actor
        return [c for c in self.repository.records.customers.values()
                if actor.can_submit_request(c.customer_id)]

    def _customer(self, customer_id: str) -> Customer:
        if not self.actor.can_submit_request(customer_id):
            raise DomainError("You cannot access this customer's records.")
        customer = self.repository.records.customers.get(customer_id)
        if customer is None:
            raise DomainError("Customer not found.")
        return customer

    def update_customer(self, customer_id: str, name: str,
                        phone: str, email: str) -> Customer:
        updated = self._customer(customer_id).update_contact_details(name, phone, email)
        records = deepcopy(self.repository.records)
        records.customers[customer_id] = updated
        self.repository.commit(records)
        return updated

    def create_request(self, customer_id: str, pickup: str,
                       destination: str,
                       parcels: list[str] | None = None) -> DeliveryRequest:
        request = self._customer(customer_id).create_request(pickup, destination)
        for description in parcels or []:
            request = request.add_parcel(description)
        records = deepcopy(self.repository.records)
        records.requests[request.request_id] = request
        self.repository.commit(records)
        return request

    def save_draft(self, request_id: str, pickup: str, destination: str,
                   parcels: list[dict[str, str]]) -> DeliveryRequest:
        """Save a whole edit form atomically, preserving existing parcel IDs."""
        request = self.get_request(request_id)
        updated = request.update_locations(pickup, destination)
        identifiers = [p["parcel_id"] for p in parcels if p.get("parcel_id")]
        if len(identifiers) != len(set(identifiers)):
            raise DomainError("A parcel cannot appear twice in a request.")
        for identifier in identifiers:
            request.find_parcel(identifier)
        for parcel in request.parcels:
            if parcel.parcel_id not in identifiers:
                updated = updated.remove_parcel(parcel.parcel_id)
        for parcel in parcels:
            if parcel.get("parcel_id"):
                updated = updated.update_parcel(parcel["parcel_id"], parcel["description"])
            else:
                updated = updated.add_parcel(parcel["description"])
        records = deepcopy(self.repository.records)
        records.requests[request_id] = updated
        self.repository.commit(records)
        return updated

    def get_request(self, request_id: str) -> DeliveryRequest:
        request = self.repository.records.requests.get(request_id)
        if request is None:
            raise DomainError("Request not found.")
        self._customer(request.customer_id)
        return request

    def list_requests(self) -> list[DeliveryRequest]:
        actor = self.actor
        return [r for r in self.repository.records.requests.values()
                if actor.can_submit_request(r.customer_id)]

    def edit_request(self, request_id: str, operation: str,
                     *values: str) -> DeliveryRequest:
        request = self.get_request(request_id)
        methods = {
            "locations": request.update_locations,
            "add": request.add_parcel,
            "remove": request.remove_parcel,
            "parcel": request.update_parcel,
        }
        if operation not in methods:
            raise DomainError("Unknown editing operation.")
        updated = methods[operation](*values)
        records = deepcopy(self.repository.records)
        records.requests[request_id] = updated
        self.repository.commit(records)
        return updated

    def create_quote(self, request_id: str, cost: str, pickup_time: str,
                     delivery_time: str) -> DeliveryQuote:
        request = self.get_request(request_id)
        quote = request.create_quote(cost, pickup_time, delivery_time, self.actor)
        records = deepcopy(self.repository.records)
        records.quotes[quote.quote_id] = quote
        records.requests[request_id] = replace(
            request, state=RequestState.QUOTED, quote_id=quote.quote_id,
        )
        self.repository.commit(records)
        return quote

    def list_quotes(self) -> list[DeliveryQuote]:
        visible = {r.request_id for r in self.list_requests()}
        return [q for q in self.repository.records.quotes.values()
                if q.request_id in visible]

    def decide_quote(self, quote_id: str, accept: bool) -> DeliveryQuote:
        quote = self.repository.records.quotes.get(quote_id)
        if quote is None:
            raise DomainError("Quote not found.")
        request = self.get_request(quote.request_id)
        operation = quote.accept if accept else quote.reject
        updated = operation(self.actor, request.customer_id)
        if updated is quote:
            return quote
        if accept:
            data = AcceptedDeliveryData.from_quote(updated, request)
            try:
                delivery_id = self.gateway.create_or_get_delivery(data)
                if not isinstance(delivery_id, str) or not delivery_id.strip():
                    raise ValueError("Delivery gateway did not return an ID")
            except Exception as exc:
                raise DomainError(
                    "Delivery handoff failed; quote remains pending. "
                    "Retry after the delivery module is available."
                ) from exc
            updated = replace(updated, delivery_id=delivery_id)
        records = deepcopy(self.repository.records)
        records.quotes[quote_id] = updated
        state = RequestState.ACCEPTED if accept else RequestState.REJECTED
        records.requests[request.request_id] = replace(request, state=state)
        self.repository.commit(records)
        return updated
