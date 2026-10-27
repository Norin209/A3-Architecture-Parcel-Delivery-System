"""Business, persistence, integration and console regression tests."""

import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from norin_delivery.console import Console
from norin_delivery.integration import DemoDeliveryGateway
from norin_delivery.models import (
    DomainError, QuoteDecision, RequestState, Role,
)
from norin_delivery.service import DeliveryApplication
from norin_delivery.storage import JsonRepository, StorageError


PASSWORD = "ExamplePass123!"


class FakeDeliveryGateway:
    """Test double obeying the documented idempotency contract."""

    def __init__(self):
        self.deliveries = {}
        self.calls = 0
        self.fail = False

    def create_or_get_delivery(self, data):
        self.calls += 1
        if self.fail:
            raise RuntimeError("Simulated downstream failure")
        if data.quote_id not in self.deliveries:
            self.deliveries[data.quote_id] = ("DEL-" + data.quote_id, data)
        return self.deliveries[data.quote_id][0]


class ModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Share only immutable seed records; each test gets its own file.
        with tempfile.TemporaryDirectory() as folder:
            app = DeliveryApplication(
                JsonRepository(Path(folder) / "seed.json"), DemoDeliveryGateway(),
            )
            app.setup_manager("manager", PASSWORD)
            cls.norin = app.register_customer(
                "Norin", "0412345678", "", "norin", PASSWORD,
            )
            cls.other = app.register_customer(
                "Other Customer", "", "other@example.com", "other", PASSWORD,
            )
            app.login("manager", PASSWORD)
            app.register_staff_account("office", PASSWORD, Role.OFFICE)
            cls.seed = deepcopy(app.repository.records)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "records.json"
        self.repo = JsonRepository(self.path)
        self.repo.commit(deepcopy(self.seed))
        self.gateway = FakeDeliveryGateway()
        self.app = DeliveryApplication(self.repo, self.gateway)
        self.app.login("norin", PASSWORD)

    def request(self):
        request = self.app.create_request(
            self.norin.customer_id, "1 Swanston St, Melbourne", "2 Glenferrie Rd, Hawthorn",
        )
        return self.app.edit_request(request.request_id, "add", "Books")

    def quote(self):
        request = self.request()
        self.app.submit_request(request.request_id)
        self.app.login("office", PASSWORD)
        return self.app.create_quote(
            request.request_id, "45.50", "2026-11-01 09:00", "2026-11-01 11:00",
        )

    def test_registration_validation_is_atomic(self):
        before = self.path.read_bytes()
        for name, phone, email in [
            ("", "0412345678", ""), ("A", "", ""),
            ("A", "wrong", ""), ("A", "", "not-an-email"),
        ]:
            with self.subTest(name=name, phone=phone, email=email):
                with self.assertRaises(DomainError):
                    self.app.register_customer(name, phone, email, "newuser", PASSWORD)
                self.assertEqual(self.path.read_bytes(), before)

    def test_usernames_are_case_insensitive(self):
        with self.assertRaises(DomainError):
            self.app.register_customer("Another", "0412345678", "", "NORIN", PASSWORD)
        self.assertEqual(self.app.login("NORIN", PASSWORD).customer_id, self.norin.customer_id)

    def test_invalid_login_clears_previous_session(self):
        with self.assertRaises(DomainError):
            self.app.login("norin", "wrong-password")
        with self.assertRaises(DomainError):
            self.app.list_requests()

    def test_passwords_are_hashed(self):
        account = self.app.actor
        self.assertNotIn(PASSWORD, self.path.read_text())
        self.assertTrue(account.verify_password(PASSWORD))
        self.assertFalse(account.verify_password("wrong"))

    def test_phone_customer_needs_no_account(self):
        self.app.login("office", PASSWORD)
        before = len(self.repo.records.accounts)
        customer = self.app.create_phone_customer("Phone Customer", "0398765432", "")
        request = self.app.create_request(customer.customer_id, "Pickup", "Destination")
        self.app.edit_request(request.request_id, "add", "Box")
        self.app.submit_request(request.request_id)
        quote = self.app.create_quote(
            request.request_id, "10", "2026-11-01 09:00", "2026-11-01 10:00",
        )
        accepted = self.app.decide_quote(quote.quote_id, True)
        self.assertEqual(len(self.repo.records.accounts), before)
        self.assertEqual(accepted.decision_recorded_by, self.app.actor.account_id)
        data = self.gateway.deliveries[quote.quote_id][1]
        self.assertEqual(data.customer_id, customer.customer_id)

    def test_customer_cannot_read_or_change_another_customer(self):
        request = self.request()
        self.app.login("other", PASSWORD)
        self.assertEqual(self.app.list_requests(), [])
        with self.assertRaises(DomainError):
            self.app.get_request(request.request_id)
        with self.assertRaises(DomainError):
            self.app.edit_request(request.request_id, "add", "Unauthorised")
        with self.assertRaises(DomainError):
            self.app.create_request(self.norin.customer_id, "A", "B")

    def test_customer_cannot_prepare_quote(self):
        request = self.request()
        with self.assertRaises(DomainError):
            self.app.create_quote(
                request.request_id, "10", "2026-11-01 09:00", "2026-11-01 10:00",
            )

    def test_submission_is_required_and_locks_the_request(self):
        request = self.request()
        self.app.login("office", PASSWORD)
        with self.assertRaisesRegex(DomainError, "submit"):
            self.app.create_quote(
                request.request_id, "10", "2026-11-01 09:00", "2026-11-01 10:00",
            )
        self.app.login("norin", PASSWORD)
        submitted = self.app.submit_request(request.request_id)
        self.assertEqual(submitted.state, RequestState.SUBMITTED)
        with self.assertRaises(DomainError):
            self.app.edit_request(request.request_id, "locations", "Changed", "Elsewhere")
        with self.assertRaises(DomainError):
            self.app.submit_request(request.request_id)
        self.app.login("other", PASSWORD)
        with self.assertRaises(DomainError):
            self.app.submit_request(request.request_id)
        self.app = DeliveryApplication(JsonRepository(self.path), self.gateway)
        self.app.login("office", PASSWORD)
        self.assertEqual(self.app.get_request(request.request_id).state,
                         RequestState.SUBMITTED)
        self.app.create_quote(request.request_id, "10", "2026-11-01 09:00",
                              "2026-11-01 10:00")

    def test_draft_editing_and_last_parcel_removal(self):
        request = self.request()
        request = self.app.edit_request(request.request_id, "add", "Clothes")
        first_id = request.parcels[0].parcel_id
        request = self.app.edit_request(request.request_id, "parcel", first_id, "Textbooks")
        self.assertEqual(request.parcels[0].description, "Textbooks")
        for parcel in request.parcels:
            self.app.edit_request(request.request_id, "remove", parcel.parcel_id)
        self.app.edit_request(request.request_id, "locations", "", "")
        updated = self.app.get_request(request.request_id)
        self.assertEqual(len(updated.validate_for_quote()), 3)
        with self.assertRaises(DomainError):
            self.app.submit_request(request.request_id)
        self.app.login("office", PASSWORD)
        with self.assertRaises(DomainError):
            self.app.create_quote(
                request.request_id, "10", "2026-11-01 09:00", "2026-11-01 10:00",
            )

    def test_blank_parcel_and_missing_parcel_fail(self):
        request = self.request()
        with self.assertRaises(DomainError):
            self.app.edit_request(request.request_id, "add", " ")
        with self.assertRaises(DomainError):
            self.app.edit_request(request.request_id, "remove", "missing")

    def test_invalid_quote_terms_leave_request_submitted(self):
        request = self.request()
        self.app.submit_request(request.request_id)
        self.app.login("office", PASSWORD)
        for cost in ("abc", "NaN", "Infinity", "0", "-1", "1.001", "1000000"):
            with self.subTest(cost=cost), self.assertRaises(DomainError):
                self.app.create_quote(
                    request.request_id, cost, "2026-11-01 09:00", "2026-11-01 10:00",
                )
        for delivery in ("bad", "2026-02-30 10:00", "2026-11-01 09:00", "2026-11-01 08:00"):
            with self.subTest(delivery=delivery), self.assertRaises(DomainError):
                self.app.create_quote(request.request_id, "10", "2026-11-01 09:00", delivery)
        self.assertEqual(self.app.get_request(request.request_id).state, RequestState.SUBMITTED)
        self.assertFalse(self.repo.records.quotes)

    def test_quoted_request_and_quote_terms_are_locked(self):
        quote = self.quote()
        with self.assertRaises(DomainError):
            self.app.edit_request(quote.request_id, "locations", "New", "Destination")
        with self.assertRaises(DomainError):
            self.app.create_quote(quote.request_id, "20", "2026-11-01 09:00", "2026-11-01 10:00")
        with self.assertRaises(FrozenInstanceError):
            quote.quoted_cost = 1

    def test_acceptance_is_idempotent_even_after_restart(self):
        quote = self.quote()
        self.app.login("norin", PASSWORD)
        accepted = self.app.decide_quote(quote.quote_id, True)
        self.assertEqual(self.app.decide_quote(quote.quote_id, True), accepted)
        self.app = DeliveryApplication(JsonRepository(self.path), self.gateway)
        self.app.login("norin", PASSWORD)
        self.assertEqual(self.app.decide_quote(quote.quote_id, True), accepted)
        self.assertEqual(self.gateway.calls, 1)
        self.assertEqual(self.app.get_request(quote.request_id).state, RequestState.ACCEPTED)
        data = self.gateway.deliveries[quote.quote_id][1]
        self.assertEqual(str(data.amount), "45.50")
        self.assertEqual(data.parcels[0][1], "Books")

    def test_other_customer_cannot_decide_even_after_acceptance(self):
        quote = self.quote()
        self.app.decide_quote(quote.quote_id, True)
        self.app.login("other", PASSWORD)
        self.assertFalse(self.app.list_quotes())
        with self.assertRaises(DomainError):
            self.app.decide_quote(quote.quote_id, True)

    def test_rejection_never_creates_delivery(self):
        quote = self.quote()
        rejected = self.app.decide_quote(quote.quote_id, False)
        self.assertEqual(rejected.decision, QuoteDecision.REJECTED)
        self.assertIsNone(rejected.delivery_id)
        self.assertFalse(self.gateway.deliveries)
        self.assertEqual(self.app.decide_quote(quote.quote_id, False), rejected)
        with self.assertRaises(DomainError):
            self.app.decide_quote(quote.quote_id, True)

    def test_accepted_quote_cannot_be_rejected(self):
        quote = self.quote()
        self.app.decide_quote(quote.quote_id, True)
        with self.assertRaises(DomainError):
            self.app.decide_quote(quote.quote_id, False)

    def test_failed_handoff_leaves_quote_pending(self):
        quote = self.quote()
        before = self.path.read_bytes()
        self.gateway.fail = True
        with self.assertRaises(DomainError):
            self.app.decide_quote(quote.quote_id, True)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.repo.records.quotes[quote.quote_id].decision, QuoteDecision.PENDING)

    def test_failed_save_preserves_memory_and_file(self):
        before = self.path.read_bytes()
        with patch("norin_delivery.storage.os.replace", side_effect=OSError("Disk unavailable")):
            with self.assertRaises(StorageError):
                self.app.create_request(self.norin.customer_id, "A", "B")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.app.list_requests())
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_save_failure_after_handoff_can_retry_without_duplicate(self):
        quote = self.quote()
        with patch("norin_delivery.storage.os.replace", side_effect=OSError("Disk unavailable")):
            with self.assertRaises(StorageError):
                self.app.decide_quote(quote.quote_id, True)
        self.assertEqual(self.repo.records.quotes[quote.quote_id].decision, QuoteDecision.PENDING)
        self.app.decide_quote(quote.quote_id, True)
        self.assertEqual(self.gateway.calls, 2)
        self.assertEqual(len(self.gateway.deliveries), 1)

    def test_manager_only_account_actions_and_history_retention(self):
        request = self.request()
        account_id = self.app.actor.account_id
        with self.assertRaises(DomainError):
            self.app.register_staff_account("newstaff", PASSWORD, Role.OFFICE)
        self.app.login("manager", PASSWORD)
        with self.assertRaises(DomainError):
            self.app.deactivate_account(self.app.actor.account_id)
        self.app.deactivate_account(account_id)
        self.assertIn(request.request_id, self.repo.records.requests)
        self.assertIn(self.norin.customer_id, self.repo.records.customers)
        with self.assertRaises(DomainError):
            self.app.login("norin", PASSWORD)

    def test_deactivated_account_cannot_use_existing_session(self):
        account_id = self.app.actor.account_id
        manager_app = DeliveryApplication(self.repo, self.gateway)
        manager_app.login("manager", PASSWORD)
        manager_app.deactivate_account(account_id)
        with self.assertRaises(DomainError):
            self.app.list_requests()

    def test_data_round_trip_restores_objects_and_decimals(self):
        quote = self.quote()
        loaded = JsonRepository(self.path)
        self.assertEqual(loaded.records, self.repo.records)
        self.assertEqual(str(loaded.records.quotes[quote.quote_id].quoted_cost), "45.50")

    def test_corrupted_file_is_not_overwritten(self):
        for text in ("not json", '{"schema_version": 99}'):
            self.path.write_text(text)
            with self.assertRaises(StorageError):
                JsonRepository(self.path)
            self.assertEqual(self.path.read_text(), text)

    def test_broken_relationship_is_rejected_on_load(self):
        self.request()
        data = json.loads(self.path.read_text())
        data["requests"][0]["customer_id"] = "missing"
        self.path.write_text(json.dumps(data))
        with self.assertRaises(StorageError):
            JsonRepository(self.path)

    def test_corrupt_saved_price_reports_storage_error(self):
        self.quote()
        data = json.loads(self.path.read_text())
        data["quotes"][0]["quoted_cost"] = "invalid decimal"
        text = json.dumps(data)
        self.path.write_text(text)
        with self.assertRaises(StorageError):
            JsonRepository(self.path)
        self.assertEqual(self.path.read_text(), text)

    def test_first_manager_cannot_be_reset(self):
        with self.assertRaises(DomainError):
            self.app.setup_manager("attacker", PASSWORD)

    def test_delivery_staff_requires_nonblank_external_staff_id(self):
        self.app.login("manager", PASSWORD)
        with self.assertRaises(DomainError):
            self.app.register_staff_account("driver", PASSWORD, Role.DELIVERY, "  ")

    def test_console_login_cancel_and_exit(self):
        self.app.logout()
        answers = iter(["wrong", "2", "norin", PASSWORD, "1", "2", "/cancel", "0", "0"])
        output = []
        reader = lambda _: next(answers)
        Console(self.app, read=reader, secret=reader, write=output.append).run()
        transcript = "\n".join(output)
        self.assertIn("Choose an option", transcript)
        self.assertIn("No delivery requests yet", transcript)
        self.assertIn("Cancelled", transcript)
        self.assertIn("Goodbye", transcript)
        self.assertFalse(self.repo.records.requests)


if __name__ == "__main__":
    unittest.main()
