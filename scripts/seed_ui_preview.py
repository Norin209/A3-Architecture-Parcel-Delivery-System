"""Create explicitly artificial preview records in a NEW, separate file."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from norin_delivery.integration import DemoDeliveryGateway
from norin_delivery.service import DeliveryApplication
from norin_delivery.storage import JsonRepository


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()
    if args.data.exists():
        raise SystemExit("Preview seeding requires a new file; nothing overwritten.")
    app = DeliveryApplication(JsonRepository(args.data), DemoDeliveryGateway())
    password = "PreviewPass123!"
    app.setup_manager("preview.manager", password)
    norin = app.register_customer(
        "Norin Demo", "", "norin@example.com", "preview.norin", password,
    )
    app.login("preview.manager", password)
    maya = app.create_phone_customer("Maya Demo", "", "maya@example.com")
    alex = app.create_phone_customer("Alex Demo", "", "alex@example.com")
    examples = [
        (norin, "18 Swanston St, Melbourne", "42 Glenferrie Rd, Hawthorn", "Books", "Accepted"),
        (maya, "7 Lygon St, Carlton", "31 Acland St, St Kilda", "Gift box", "Rejected"),
        (norin, "18 Swanston St, Melbourne", "9 Church St, Richmond", "Clothing", "Pending"),
        (alex, "64 Brunswick St, Fitzroy", "22 Chapel St, Prahran", "Art supplies", "Pending"),
        (norin, "18 Swanston St, Melbourne", "24 High St, Northcote", "Kitchen items", "Draft"),
    ]
    for index, (customer, pickup, destination, parcel, decision) in enumerate(examples):
        request = app.create_request(customer.customer_id, pickup, destination, [parcel])
        if decision != "Draft":
            quote = app.create_quote(request.request_id, str(35 + index * 12) + ".50",
                                     "2026-11-01 09:00", "2026-11-01 11:00")
            if decision in ("Accepted", "Rejected"):
                app.decide_quote(quote.quote_id, decision == "Accepted")
    print(f"Artificial preview records: {args.data}")
    print("Preview logins: preview.manager or preview.norin; password: PreviewPass123!")


if __name__ == "__main__":
    main()
