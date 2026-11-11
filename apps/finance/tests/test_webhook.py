from unittest.mock import patch

from apps.finance.models import Payment, StripeEvent
from apps.finance.tests.base import FinanceTestBase

URL = "/api/v1/finance/stripe/webhook/"


def _event(event_id, type_, obj):
    return {"id": event_id, "type": type_, "data": {"object": obj}}


class StripeWebhookTests(FinanceTestBase):
    def _post(self, event):
        with patch("apps.finance.webhook.stripe.Webhook.construct_event", return_value=event):
            self.client.credentials()
            return self.client.post(URL, data=b"{}", content_type="application/json")

    def setUp(self):
        super().setUp()
        self.sub = self.create_subscription(self.create_plan())
        self.sub.stripe_subscription_id = "sub_1"
        self.sub.save()

    def test_failed_payment_event_is_deduplicated(self):
        ev = _event("evt_1", "invoice.payment_failed", {"id": "in_1", "subscription": "sub_1", "amount_due": 2900})
        self.assertEqual(self._post(ev).status_code, 200)
        self.assertEqual(self._post(ev).status_code, 200)
        self.assertEqual(Payment.objects.filter(status="failed").count(), 1)
        self.assertEqual(StripeEvent.objects.filter(event_id="evt_1").count(), 1)

    def test_invoice_paid_records_renewal_once(self):
        obj = {"id": "in_2", "subscription": "sub_1", "amount_paid": 2900,
               "lines": {"data": [{"period": {"start": 1_800_000_000, "end": 1_802_592_000}}]}}
        self._post(_event("evt_2", "invoice.paid", obj))
        self._post(_event("evt_3", "invoice.paid", obj))  # different event, same invoice
        self.assertEqual(Payment.objects.filter(stripe_invoice_id="in_2", status="paid").count(), 1)

    def test_checkout_without_metadata_does_not_500(self):
        res = self._post(_event("evt_4", "checkout.session.completed", {"metadata": {}}))
        self.assertEqual(res.status_code, 200)

    def test_unknown_event_type_is_ignored(self):
        self.assertEqual(self._post(_event("evt_5", "customer.created", {})).status_code, 200)
        self.assertFalse(StripeEvent.objects.filter(event_id="evt_5").exists())

    def test_invalid_signature_rejected(self):
        import stripe
        self.client.credentials()
        with patch("apps.finance.webhook.stripe.Webhook.construct_event",
                   side_effect=stripe.SignatureVerificationError("bad", "sig")):
            res = self.client.post(URL, data=b"{}", content_type="application/json")
        self.assertEqual(res.status_code, 400)

    def test_subscription_updated_with_period_timestamps(self):
        obj = {"id": "sub_1", "current_period_start": 1_800_000_000, "current_period_end": 1_802_592_000,
               "cancel_at_period_end": True, "items": {"data": []}}
        self.assertEqual(self._post(_event("evt_6", "customer.subscription.updated", obj)).status_code, 200)
        self.sub.refresh_from_db()
        self.assertTrue(self.sub.cancel_at_period_end)
