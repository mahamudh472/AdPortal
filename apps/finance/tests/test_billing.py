"""
Tests for billing endpoints:
  POST /api/v1/finance/buy-plan/?org_id=
  GET  /api/v1/finance/get-current-plan/?org_id=
  GET  /api/v1/finance/billing-history/?org_id=
"""
from unittest.mock import MagicMock, patch

from apps.finance.tests.base import FinanceTestBase

BASE = "/api/v1/finance"
FAKE_SESSION_ID = "cs_test_fake_session_id"
FAKE_CLIENT_SECRET = "cs_test_fake_session_id_secret_123"


def _mock_stripe_session():
    sess = MagicMock()
    sess.id = FAKE_SESSION_ID
    sess.client_secret = FAKE_CLIENT_SECRET
    return sess


class BuyPlanTests(FinanceTestBase):
    """Tests for POST /api/v1/finance/buy-plan/"""

    def _url(self):
        return f"{BASE}/buy-plan/?org_id={self.org_id}"

    @patch("apps.finance.views.stripe.checkout.Session.create", return_value=_mock_stripe_session())
    def test_buy_plan_success_returns_embedded_checkout_data(self, mock_stripe):
        plan = self.create_plan("starter")
        res = self.client.post(self._url(), {"plan_id": plan.id}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("checkout_session_id", res.data)
        self.assertIn("client_secret", res.data)
        self.assertEqual(res.data["checkout_session_id"], FAKE_SESSION_ID)
        self.assertEqual(res.data["client_secret"], FAKE_CLIENT_SECRET)
        mock_stripe.assert_called_once()

        stripe_kwargs = mock_stripe.call_args.kwargs
        self.assertEqual(stripe_kwargs.get("ui_mode"), "embedded")
        self.assertIn("return_url", stripe_kwargs)
        self.assertNotIn("payment_method_types", stripe_kwargs)

    @patch("apps.finance.views.stripe.checkout.Session.create", return_value=_mock_stripe_session())
    def test_buy_plan_already_active_subscription_returns_200_exists_msg(self, mock_stripe):
        plan = self.create_plan("growth", price=79.00)
        self.create_subscription(plan, status="active")
        res = self.client.post(self._url(), {"plan_id": plan.id}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("You are already subscribed to this plan.", res.data.get("message", ""))
        mock_stripe.assert_not_called()

    def test_buy_plan_missing_plan_id_returns_400(self):
        res = self.client.post(self._url(), {}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_buy_plan_invalid_plan_id_returns_400(self):
        res = self.client.post(self._url(), {"plan_id": 99999}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_buy_plan_as_member_returns_403(self):
        """Only ADMIN or OWNER can purchase a plan."""
        member = self.create_user(email="plain_member@example.com")
        self.add_member(member, self.org, role="MEMBER")
        self.authenticate(member)
        plan = self.create_plan("starter")
        res = self.client.post(self._url(), {"plan_id": plan.id}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_buy_plan_unauthenticated_returns_401(self):
        self.client.credentials()
        plan = self.create_plan("starter")
        res = self.client.post(self._url(), {"plan_id": plan.id}, format="json")
        self.assertEqual(res.status_code, 401)


class GetCurrentPlanTests(FinanceTestBase):
    """Tests for GET /api/v1/finance/get-current-plan/"""

    def _url(self):
        return f"{BASE}/get-current-plan/?org_id={self.org_id}"

    def test_get_current_plan_with_active_subscription(self):
        plan = self.create_plan("starter")
        self.create_subscription(plan, status="active")
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["plan_name"], "starter")
        self.assertIn("campaign_limit", res.data)

    def test_get_current_plan_no_subscription_returns_404(self):
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 404)

    def test_get_current_plan_non_member_returns_403(self):
        other = self.create_user(email="outsider_plan@example.com")
        self.authenticate(other)
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 403)

    def test_get_current_plan_unauthenticated_returns_401(self):
        self.client.credentials()
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 401)


class BillingHistoryTests(FinanceTestBase):
    """Tests for GET /api/v1/finance/billing-history/"""

    def _url(self):
        return f"{BASE}/billing-history/?org_id={self.org_id}"

    def test_billing_history_returns_empty_list(self):
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 0)

    def test_billing_history_returns_payments(self):
        plan = self.create_plan("growth", price=79.00)
        sub = self.create_subscription(plan)
        self.create_payment(sub, amount=79.00)
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(str(res.data[0]["amount"]), "79.00")

    def test_billing_history_member_without_admin_returns_403(self):
        """Only ADMIN / OWNER may view billing history."""
        member = self.create_user(email="billing_member@example.com")
        self.add_member(member, self.org, role="MEMBER")
        self.authenticate(member)
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 403)

    def test_billing_history_unauthenticated_returns_401(self):
        self.client.credentials()
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 401)


class BillingHistoryShapeTests(FinanceTestBase):
    """The billing table renders these fields directly."""

    def _url(self):
        return f"{BASE}/billing-history/?org_id={self.org_id}"

    def test_row_contains_display_fields(self):
        plan = self.create_plan("starter", price=79)
        sub = self.create_subscription(plan)
        payment = self.create_payment(sub, amount=79)

        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 200)
        row = res.data[0]
        self.assertEqual(row["id"], payment.id)
        self.assertEqual(row["description"], "Starter Plan - Monthly Subscription")
        self.assertEqual(row["status"], "Paid")
        self.assertEqual(float(row["amount"]), 79.0)
        self.assertIn("start", row["period"])
        self.assertIn("end", row["period"])
        self.assertFalse(row["has_invoice"])

    def test_has_invoice_when_stripe_invoice_exists(self):
        sub = self.create_subscription(self.create_plan("growth", price=199))
        payment = self.create_payment(sub, amount=199)
        payment.stripe_invoice_id = "in_123"
        payment.save()
        res = self.client.get(self._url())
        self.assertTrue(res.data[0]["has_invoice"])


class InvoiceDownloadTests(FinanceTestBase):
    @patch("apps.finance.views.stripe.Invoice.retrieve", return_value={"invoice_pdf": "https://stripe.test/in_1.pdf"})
    def test_single_invoice_returns_url(self, mock_retrieve):
        sub = self.create_subscription(self.create_plan("starter"))
        payment = self.create_payment(sub)
        payment.stripe_invoice_id = "in_1"
        payment.save()
        res = self.client.get(f"{BASE}/invoices/{payment.id}/download/?org_id={self.org_id}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["url"], "https://stripe.test/in_1.pdf")

    def test_single_invoice_without_stripe_invoice_returns_404(self):
        sub = self.create_subscription(self.create_plan("starter"))
        payment = self.create_payment(sub)
        res = self.client.get(f"{BASE}/invoices/{payment.id}/download/?org_id={self.org_id}")
        self.assertEqual(res.status_code, 404)

    def test_download_all_without_invoices_returns_404(self):
        res = self.client.get(f"{BASE}/invoices/download-all/?org_id={self.org_id}")
        self.assertEqual(res.status_code, 404)

    @patch("requests.get")
    @patch("apps.finance.views.stripe.Invoice.retrieve", return_value={"invoice_pdf": "https://stripe.test/in_1.pdf"})
    def test_download_all_returns_zip(self, mock_retrieve, mock_get):
        import io
        import zipfile

        mock_get.return_value = MagicMock(content=b"%PDF-1.4 fake", raise_for_status=lambda: None)
        sub = self.create_subscription(self.create_plan("starter"))
        payment = self.create_payment(sub)
        payment.stripe_invoice_id = "in_1"
        payment.save()

        res = self.client.get(f"{BASE}/invoices/download-all/?org_id={self.org_id}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "application/zip")
        archive = zipfile.ZipFile(io.BytesIO(res.content))
        self.assertEqual(len(archive.namelist()), 1)

    def test_other_org_payment_not_downloadable(self):
        other_owner = self.create_user(email="other_fin_owner@example.com")
        other_org = self.create_organization(other_owner)
        from apps.finance.models import Payment
        payment = Payment.objects.create(
            organization=other_org, amount=10, status="paid", stripe_invoice_id="in_x"
        )
        res = self.client.get(f"{BASE}/invoices/{payment.id}/download/?org_id={self.org_id}")
        self.assertEqual(res.status_code, 404)
