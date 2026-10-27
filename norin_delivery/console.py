"""Small role-aware console interface; business rules stay in the models."""

import argparse
import sys
from getpass import getpass
from pathlib import Path

from .integration import DemoDeliveryGateway
from .models import DomainError, Role
from .service import DeliveryApplication
from .storage import JsonRepository, StorageError


class Cancelled(Exception):
    """The user left an input form without submitting it."""


def read_password(prompt: str) -> str:
    """Hide console input; read redirected stdin without Windows console I/O."""
    if sys.stdin.isatty():
        return getpass(prompt)
    return input(prompt)


class Console:
    def __init__(self, app: DeliveryApplication, read=input,
                 secret=read_password, write=print):
        self.app = app
        self.read = read
        self.secret = secret
        self.write = write

    def ask(self, label: str, hidden: bool = False) -> str:
        value = (self.secret if hidden else self.read)(label + ": ")
        if value.strip().casefold() == "/cancel":
            raise Cancelled
        return value if hidden else value.strip()

    def password(self) -> str:
        value = self.ask("Password (at least 8 characters)", hidden=True)
        if value != self.ask("Confirm password", hidden=True):
            raise DomainError("Passwords do not match.")
        return value

    def select(self, items: list, describe):
        if not items:
            raise DomainError("No matching records yet.")
        for index, item in enumerate(items, 1):
            self.write(f"{index}. {describe(item)}")
        choice = self.ask("Choose record number, or /cancel")
        if not choice.isdigit() or not 1 <= int(choice) <= len(items):
            raise DomainError("Choose a number from the displayed list.")
        return items[int(choice) - 1]

    def confirm(self, label: str) -> bool:
        answer = self.ask(label + " [y/n]").casefold()
        if answer not in ("y", "n"):
            raise DomainError("Enter y or n.")
        return answer == "y"

    def contact_fields(self) -> tuple[str, str, str]:
        return (
            self.ask("Customer name"),
            self.ask("Phone (optional if email supplied)"),
            self.ask("Email (optional if phone supplied)"),
        )

    def register(self) -> None:
        fields = self.contact_fields()
        username = self.ask("New username")
        password = self.password()
        if self.confirm(f"Create customer {fields[0]} and account {username}?"):
            customer = self.app.register_customer(*fields, username, password)
            self.write(f"Registered {customer.customer_id}. You may now sign in.")

    def login(self) -> None:
        username = self.ask("Username")
        actor = self.app.login(username, self.ask("Password", hidden=True))
        self.write(f"Signed in: {actor.username} ({actor.role.value})")

    def customer(self):
        return self.select(
            self.app.list_customers(),
            lambda c: f"{c.display_name} | {c.customer_id} | {c.phone} {c.email}",
        )

    def request(self):
        return self.select(self.app.list_requests(), self.request_label)

    @staticmethod
    def request_label(request) -> str:
        return (f"{request.request_id} | {request.state.value} | "
                f"{request.pickup_address or '(empty pickup)'} -> "
                f"{request.destination_address or '(empty destination)'}")

    @staticmethod
    def quote_label(quote) -> str:
        return (f"{quote.quote_id} | {quote.request_id} | "
                f"AUD {quote.quoted_cost:.2f} | {quote.decision.value}")

    def show_requests(self) -> None:
        requests = self.app.list_requests()
        if not requests:
            self.write("No delivery requests yet.")
        for request in requests:
            self.write(self.request_label(request))
            self.write(f"  Customer: {request.customer_id}")
            for parcel in request.parcels:
                self.write("  " + parcel.get_details())
            errors = request.validate_for_quote()
            self.write("  " + (" ".join(errors) if errors else "Request information complete."))

    def new_request(self) -> None:
        customer = self.customer()
        pickup = self.ask("Pickup address (may be blank while drafting)")
        destination = self.ask("Destination address (may be blank while drafting)")
        if self.confirm(f"Save draft for {customer.display_name}: {pickup} -> {destination}?"):
            request = self.app.create_request(customer.customer_id, pickup, destination)
            self.write(f"Draft saved: {request.request_id}. Use Edit draft to add parcels.")

    def edit_request(self) -> None:
        request = self.request()
        request.require_draft()
        self.write("1 Locations | 2 Add parcel | 3 Edit parcel | 4 Remove parcel | 5 Validate")
        choice = self.ask("Action")
        if choice == "1":
            pickup = self.ask("New pickup address")
            destination = self.ask("New destination address")
            self.app.edit_request(request.request_id, "locations", pickup, destination)
        elif choice == "2":
            self.app.edit_request(request.request_id, "add", self.ask("Parcel description"))
        elif choice in ("3", "4"):
            parcel = self.select(list(request.parcels), lambda p: p.get_details())
            if choice == "3":
                self.app.edit_request(request.request_id, "parcel", parcel.parcel_id,
                                      self.ask("New parcel description"))
            elif self.confirm("Remove this parcel from the draft?"):
                self.app.edit_request(request.request_id, "remove", parcel.parcel_id)
            else:
                self.write("Nothing changed.")
                return
        elif choice == "5":
            errors = request.validate_for_quote()
            self.write(" ".join(errors) if errors else "Ready for office-staff quotation.")
            return
        else:
            raise DomainError("Choose an action from 1 to 5.")
        self.write("Draft updated and saved.")

    def show_quotes(self) -> None:
        quotes = self.app.list_quotes()
        if not quotes:
            self.write("No quotes yet.")
        for quote in quotes:
            self.write(self.quote_label(quote))
            self.write(f"  Pickup: {quote.estimated_pickup:%Y-%m-%d %H:%M}")
            self.write(f"  Delivery: {quote.estimated_delivery:%Y-%m-%d %H:%M}")
            self.write("  Estimates use Melbourne local time.")
            self.write(f"  Prepared by: {quote.prepared_by} at {quote.prepared_at}")
            if quote.decision_at:
                self.write(f"  Decision by: {quote.decision_recorded_by} at {quote.decision_at}")
            if quote.delivery_id:
                self.write(f"  Delivery reference: {quote.delivery_id}")

    def decide(self) -> None:
        quote = self.select(self.app.list_quotes(), self.quote_label)
        request = self.app.get_request(quote.request_id)
        customer = next(c for c in self.app.list_customers()
                        if c.customer_id == request.customer_id)
        self.write(f"Decision belongs to {customer.display_name} ({customer.customer_id}).")
        self.write(f"Pickup: {quote.estimated_pickup}; delivery: {quote.estimated_delivery}")
        choice = self.ask("Enter accept or reject").casefold()
        if choice not in ("accept", "reject"):
            raise DomainError("Enter accept or reject.")
        if self.confirm(f"Record {choice} for this customer's quote?"):
            result = self.app.decide_quote(quote.quote_id, choice == "accept")
            self.write(f"Quote {result.decision.value}; decision saved.")
            if result.delivery_id:
                self.write(f"Delivery reference: {result.delivery_id}")
                if result.delivery_id.startswith("DEMO-"):
                    self.write("DEMO handoff only; no actual delivery job was created.")

    def update_contact(self) -> None:
        customer = self.customer()
        fields = self.contact_fields()
        if self.confirm("Replace this customer's contact details?"):
            self.app.update_customer(customer.customer_id, *fields)
            self.write("Customer updated; request ownership and history retained.")

    def phone_customer(self) -> None:
        fields = self.contact_fields()
        if self.confirm(f"Create phone customer {fields[0]} without an online account?"):
            customer = self.app.create_phone_customer(*fields)
            self.write(f"Customer saved: {customer.customer_id}")

    def quote(self) -> None:
        request = self.request()
        cost = self.ask("Quoted cost in AUD (e.g. 45.50)")
        pickup = self.ask("Estimated pickup YYYY-MM-DD HH:MM (Melbourne local)")
        delivery = self.ask("Estimated delivery YYYY-MM-DD HH:MM (Melbourne local)")
        if self.confirm(f"Issue AUD {cost} quote; lock request against editing?"):
            quote = self.app.create_quote(request.request_id, cost, pickup, delivery)
            self.write(f"Quote saved: {quote.quote_id}. Awaiting customer's decision.")

    def staff_account(self) -> None:
        role = self.select([Role.OFFICE, Role.MANAGER, Role.DELIVERY], lambda r: r.value)
        username = self.ask("New staff username")
        password = self.password()
        staff_id = None
        if role == Role.DELIVERY:
            staff_id = self.ask("Existing DeliveryStaff ID from Mekno's module")
        if self.confirm(f"Create {role.value} account {username}?"):
            account = self.app.register_staff_account(username, password, role, staff_id)
            self.write(f"Staff account saved: {account.account_id}")

    def deactivate(self) -> None:
        account = self.select(
            self.app.list_accounts(),
            lambda a: f"{a.username} | {a.role.value} | active={a.active}",
        )
        if self.confirm(f"Deactivate {account.username} and retain history?"):
            self.app.deactivate_account(account.account_id)
            self.write("Account deactivated. Business records retained.")

    def run(self) -> None:
        self.write("YOUR ORDER WE DELIVER - Norin's module")
        self.write("Customer / account / request / parcel / quotation")
        self.write("DEMO delivery handoff: Mekno's Delivery module is not connected.")
        self.write("Enter /cancel at any input to return. Changes save after each operation.")
        try:
            while self.app.needs_setup:
                try:
                    self.write("First run: create the initial manager account.")
                    username = self.ask("Manager username")
                    self.app.setup_manager(username, self.password())
                    self.write("Manager created. Sign in below.")
                except (DomainError, StorageError) as exc:
                    self.write(f"Error: {exc}")
                except Cancelled:
                    return
            while True:
                try:
                    if not self.app.signed_in:
                        self.write("\n1 Register customer | 2 Sign in | 0 Exit")
                        choice = self.ask("Choice")
                        if choice == "0":
                            break
                        actions = {"1": self.register, "2": self.login}
                    else:
                        actor = self.app.actor
                        self.write(f"\n{actor.username} - {actor.role.value}")
                        actions = {
                            "1": self.show_requests, "2": self.new_request,
                            "3": self.edit_request, "4": self.show_quotes,
                            "5": self.decide, "6": self.update_contact,
                            "0": self.app.logout,
                        }
                        self.write("1 Requests | 2 New draft | 3 Edit draft | 4 Quotes")
                        self.write("5 Accept/reject quote | 6 Contact details | 0 Sign out")
                        if actor.role in (Role.OFFICE, Role.MANAGER):
                            actions.update({"7": self.phone_customer, "8": self.quote})
                            self.write("7 Add phone customer | 8 Prepare quote")
                        if actor.role == Role.MANAGER:
                            actions.update({"9": self.staff_account, "10": self.deactivate})
                            self.write("9 Register staff account | 10 Deactivate account")
                        choice = self.ask("Choice")
                    if choice not in actions:
                        raise DomainError("Choose an option from the displayed menu.")
                    actions[choice]()
                except Cancelled:
                    self.write("Cancelled. This form made no changes.")
                except (DomainError, StorageError) as exc:
                    self.write(f"Error: {exc}")
        except (EOFError, KeyboardInterrupt):
            self.write("\nInput ended; unfinished form discarded.")
        finally:
            self.app.logout()
            self.write("Goodbye. Successfully saved records will be available next time.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Norin's A3 console module")
    root = Path(__file__).resolve().parents[1]
    if root.is_file():  # Running from the executable .pyz archive.
        root = root.parent
    default = root / "data" / "records.json"
    parser.add_argument("--data", type=Path, default=default,
                        help="JSON data file (one running console per file)")
    args = parser.parse_args()
    try:
        app = DeliveryApplication(JsonRepository(args.data), DemoDeliveryGateway())
        Console(app).run()
        return 0
    except StorageError as exc:
        print(f"Cannot start: {exc}")
        return 1
