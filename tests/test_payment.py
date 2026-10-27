"""Tests for Tola's payment record and accepted-quote comparison."""

import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from decimal import Decimal

from norin_delivery.models import DeliveryQuote, DomainError, QuoteDecision
from tola_payment.payment import Payment, PaymentComparison


class PaymentTests(unittest.TestCase):
    def accepted_quote(self, delivery_id="DEL-100"):
        return DeliveryQuote(
            quote_id="QUO-100",
            request_id="REQ-100",
            quoted_cost=Decimal("45.50"),
            estimated_pickup=datetime(2026, 11, 1, 9, 0),
            estimated_delivery=datetime(2026, 11, 1, 11, 0),
            prepared_by="ACC-OFFICE",
            prepared_at="2026-10-27T01:00:00+00:00",
            decision=QuoteDecision.ACCEPTED,
            decision_at="2026-10-27T02:00:00+00:00",
            decision_recorded_by="ACC-CUSTOMER",
            delivery_id=delivery_id,
        )

    def test_exact_collection_matches_accepted_quote(self):
        quote = self.accepted_quote()

        payment = Payment.record_collection("DEL-100", quote, "45.50")

        self.assertEqual(payment.delivery_id, "DEL-100")
        self.assertEqual(payment.quote_id, quote.quote_id)
        self.assertEqual(payment.amount_received, Decimal("45.50"))
        self.assertEqual(payment.accepted_amount, Decimal("45.50"))
        self.assertEqual(payment.comparison_result, PaymentComparison.MATCH)
        self.assertEqual(quote.quoted_cost, Decimal("45.50"))
        self.assertIsNotNone(payment.collected_at.tzinfo)

    def test_mismatch_is_recorded_without_changing_accepted_terms(self):
        quote = self.accepted_quote()

        payment = Payment.record_collection("DEL-100", quote, "40.00")

        self.assertEqual(payment.comparison_result, PaymentComparison.MISMATCH)
        self.assertEqual(payment.amount_received, Decimal("40.00"))
        self.assertEqual(payment.accepted_amount, Decimal("45.50"))
        self.assertEqual(quote.quoted_cost, Decimal("45.50"))

    def test_unaccepted_quote_cannot_be_used_for_payment(self):
        quote = self.accepted_quote()
        pending = replace(
            quote,
            decision=QuoteDecision.PENDING,
            decision_at=None,
            decision_recorded_by=None,
            delivery_id=None,
        )

        with self.assertRaises(DomainError):
            Payment.record_collection("DEL-100", pending, "45.50")

    def test_delivery_must_match_accepted_quote_delivery(self):
        quote = self.accepted_quote()

        with self.assertRaises(DomainError):
            Payment.record_collection("DEL-OTHER", quote, "45.50")

    def test_invalid_collection_amount_is_rejected(self):
        quote = self.accepted_quote()

        for value in ("0", "-1", "1.001", "NaN", "bad"):
            with self.subTest(value=value), self.assertRaises(DomainError):
                Payment.record_collection("DEL-100", quote, value)

    def test_payment_record_is_immutable(self):
        payment = Payment.record_collection(
            "DEL-100", self.accepted_quote(), "45.50",
        )

        with self.assertRaises(FrozenInstanceError):
            payment.amount_received = Decimal("1.00")


if __name__ == "__main__":
    unittest.main()
