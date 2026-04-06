"""
Tests for billing endpoints:
  POST /api/v1/finance/buy-plan/?org_id=
  GET  /api/v1/finance/get-current-plan/?org_id=
  GET  /api/v1/finance/billing-history/?org_id=
"""
from unittest.mock import MagicMock, patch

from finance.tests.base import FinanceTestBase

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

    @patch("finance.views.stripe.checkout.Session.create", return_value=_mock_stripe_session())
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
        self.assertEqual(stripe_kwargs.get("automatic_payment_methods"), {"enabled": True})
        self.assertIn("return_url", stripe_kwargs)
        self.assertNotIn("payment_method_types", stripe_kwargs)

    @patch("finance.views.stripe.checkout.Session.create", return_value=_mock_stripe_session())
    def test_buy_plan_already_active_subscription_returns_200_exists_msg(self, mock_stripe):
        plan = self.create_plan("growth", price=79.00)
        self.create_subscription(plan, status="active")
        res = self.client.post(self._url(), {"plan_id": plan.id}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Subscription already exists", res.data.get("message", ""))
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
