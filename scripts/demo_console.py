"""Run a repeatable UI walkthrough with fake inputs and temporary records.

This is an automated demonstration, not a manual user test. It never
reads or modifies the real data/records.json file.
"""

import sys
import tempfile
from pathlib import Path

# Allow `python scripts/demo_console.py` without installing a package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from norin_delivery.console import Console
from norin_delivery.integration import DemoDeliveryGateway
from norin_delivery.models import QuoteDecision
from norin_delivery.service import DeliveryApplication
from norin_delivery.storage import JsonRepository


def main() -> None:
    password = "DemoPass123!"
    pickup = "2026-11-01 09:00"
    delivery = "2026-11-01 11:00"
    answers = iter([
        "manager", password, password,
        "1", "Norin Demo", "0412345678", "", "norin", password, password, "y",
        "2", "norin", password,
        "1",
        "2", "1", "1 Swanston St, Melbourne", "", "y",
        "3", "1", "5",
        "3", "1", "1", "1 Swanston St, Melbourne", "2 Glenferrie Rd, Hawthorn",
        "3", "1", "2", "",
        "3", "1", "2", "Books",
        "3", "1", "2", "Clothes",
        "3", "1", "3", "2", "Clothes - fragile",
        "3", "1", "4", "2", "y",
        "1",
        "11", "1", "y",
        "0",
        "2", "manager", password,
        "8", "1", "0", pickup, delivery, "y",
        "8", "1", "45.50", pickup, delivery, "y",
        "0",
        "2", "norin", password,
        "4",
        "5", "1", "accept", "y",
        "5", "1", "accept", "y",
        "0", "0",
    ])

    def read(prompt: str) -> str:
        value = next(answers)
        print(prompt + value)
        return value

    def secret(prompt: str) -> str:
        value = next(answers)
        print(prompt + "[hidden demo password]")
        return value

    print("AUTOMATED CONSOLE WALKTHROUGH - temporary demo data only")
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "records.json"
        app = DeliveryApplication(JsonRepository(path), DemoDeliveryGateway())
        Console(app, read=read, secret=secret).run()
        assert next(answers, None) is None, "Walkthrough did not consume all inputs"
        restarted = DeliveryApplication(JsonRepository(path), DemoDeliveryGateway())
        restarted.login("norin", password)
        requests = restarted.list_requests()
        quotes = restarted.list_quotes()
        assert len(requests) == len(quotes) == 1
        assert len(requests[0].parcels) == 1
        assert quotes[0].decision == QuoteDecision.ACCEPTED
        assert str(quotes[0].quoted_cost) == "45.50"
        assert restarted.decide_quote(quotes[0].quote_id, True) == quotes[0]
        print("PASS: edited request, validation, quotation, repeated acceptance and restart.")
        print("DEMO reference only; real delivery integration remains outstanding.")


if __name__ == "__main__":
    main()
