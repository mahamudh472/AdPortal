"""
Tests for dashboard/analytics/integration endpoints:
  GET /api/v1/main/dashboard/?org_id=
  GET /api/v1/main/analytics/?org_id=
  GET /api/v1/main/integrations-status/?org_id=
"""
from main.tests.base import MainTestBase


class DashboardTests(MainTestBase):
    """Tests for GET /api/v1/main/dashboard/"""

    def _url(self):
        return "/api/v1/main/dashboard/"

    def test_dashboard_returns_200(self):
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)

    def test_dashboard_invalid_org_returns_400(self):
        res = self.client.get(self._url(), {"org_id": "bad_id_000"})
        self.assertIn(res.status_code, [400, 403])

    def test_dashboard_non_member_returns_403(self):
        other = self.create_user(email="stranger_dash@example.com")
        self.authenticate(other)
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 403)

    def test_dashboard_unauthenticated_returns_401(self):
        self.client.credentials()
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 401)


class AnalyticsTests(MainTestBase):
    """Tests for GET /api/v1/main/analytics/"""

    def _url(self):
        return "/api/v1/main/analytics/"

    def test_analytics_returns_200(self):
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)

    def test_analytics_invalid_org_returns_400(self):
        res = self.client.get(self._url(), {"org_id": "invalid_org"})
        self.assertIn(res.status_code, [400, 403])

    def test_analytics_non_member_returns_403(self):
        other = self.create_user(email="stranger_analytics@example.com")
        self.authenticate(other)
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 403)


class IntegrationStatusTests(MainTestBase):
    """Tests for GET /api/v1/main/integrations-status/"""

    def _url(self):
        return "/api/v1/main/integrations-status/"

    def test_integrations_status_always_returns_3_platforms(self):
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        platforms = {i["platform"] for i in res.data["integrations"]}
        self.assertEqual(platforms, {"META", "GOOGLE", "TIKTOK"})

    def test_integrations_status_with_existing_integration(self):
        """Connected integration shows status=True."""
        self.create_integration("META")
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        meta = next(i for i in res.data["integrations"] if i["platform"] == "META")
        self.assertTrue(meta["status"])

    def test_integrations_status_without_integrations(self):
        """All platforms show status=False when no integrations exist."""
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        for integration_info in res.data["integrations"]:
            self.assertFalse(integration_info["status"])

    def test_integrations_status_invalid_org_returns_400(self):
        res = self.client.get(self._url(), {"org_id": "bad_id"})
        self.assertIn(res.status_code, [400, 403])
