"""
Tests for plan listing endpoint:
  GET /api/v1/finance/get-plans/
"""
from apps.finance.models import Plan
from apps.finance.tests.base import FinanceTestBase


class PlanListTests(FinanceTestBase):
    """Tests for GET /api/v1/finance/get-plans/"""

    def _url(self):
        return "/api/v1/finance/get-plans/"

    def test_get_plans_returns_200(self):
        self.create_plan("starter")
        self.create_plan("growth", price=79.00)
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(len(res.data), 2)

    def test_get_plans_only_returns_active_plans(self):
        """Inactive plans must be excluded."""
        self.create_plan("starter")
        self.create_plan("scale", price=199.00, active=False)
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 200)
        names = [p["name"] for p in res.data]
        self.assertNotIn("scale", names)

    def test_get_plans_empty_when_none_active(self):
        Plan.objects.all().delete()
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 0)

    def test_get_plans_no_auth_required(self):
        """Plans endpoint is public."""
        self.client.credentials()
        self.create_plan("starter")
        res = self.client.get(self._url())
        self.assertNotEqual(res.status_code, 401)
