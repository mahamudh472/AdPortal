"""
Tests for sync endpoints:
  POST /api/v1/main/sync-ads/?org_id=
  POST /api/v1/main/sync-analytics/?org_id=
"""
from unittest.mock import patch

from apps.main.tests.base import MainTestBase

BASE = "/api/v1/main"


class SyncAdsTests(MainTestBase):
    """Tests for POST /api/v1/main/sync-ads/"""

    def _url(self):
        return f"{BASE}/sync-ads/?org_id={self.org_id}"

    @patch("apps.main.services.campaign.sync_ads_task")
    def test_sync_ads_with_integration_dispatches_task(self, mock_task):
        mock_task.delay.return_value = None
        self.create_integration("META")
        res = self.client.post(self._url(), {}, format="json")
        self.assertEqual(res.status_code, 200)
        mock_task.delay.assert_called_once()

    def test_sync_ads_no_integrations_returns_400(self):
        res = self.client.post(self._url(), {}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_sync_ads_invalid_org_returns_400(self):
        res = self.client.post(f"{BASE}/sync-ads/?org_id=bad_org", {}, format="json")
        self.assertIn(res.status_code, [400, 403])

    def test_sync_ads_unauthenticated_returns_401(self):
        self.client.credentials()
        res = self.client.post(self._url(), {}, format="json")
        self.assertEqual(res.status_code, 401)

    @patch("apps.main.services.campaign.sync_ads_task")
    def test_sync_ads_skips_google_integration(self, mock_task):
        """Google is not yet supported — no tasks should be dispatched for it."""
        mock_task.delay.return_value = None
        self.create_integration("GOOGLE")
        res = self.client.post(self._url(), {}, format="json")
        # GOOGLE is skipped → behaves like no integrations
        self.assertEqual(res.status_code, 400)
        mock_task.delay.assert_not_called()


class SyncAnalyticsTests(MainTestBase):
    """Tests for POST /api/v1/main/sync-analytics/"""

    def _url(self):
        return f"{BASE}/sync-analytics/?org_id={self.org_id}"

    @patch("apps.main.services.campaign.sync_analytics_task")
    def test_sync_analytics_with_meta_integration(self, mock_task):
        mock_task.delay.return_value = None
        self.create_integration("META")
        res = self.client.post(
            self._url(),
            {"start_date": "2026-01-01", "end_date": "2026-01-31"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)

    def test_sync_analytics_no_active_integrations_returns_400(self):
        res = self.client.post(self._url(), {}, format="json")
        self.assertEqual(res.status_code, 400)

    @patch("apps.main.services.campaign.sync_analytics_task")
    def test_sync_analytics_platform_filter(self, mock_task):
        mock_task.delay.return_value = None
        self.create_integration("META")
        self.create_integration("TIKTOK")
        res = self.client.post(self._url(), {"platform": "META"}, format="json")
        self.assertEqual(res.status_code, 200)
        # Only 1 call for META
        self.assertEqual(mock_task.delay.call_count, 1)

    def test_sync_analytics_invalid_org_returns_400(self):
        res = self.client.post(f"{BASE}/sync-analytics/?org_id=invalid_org", {}, format="json")
        self.assertIn(res.status_code, [400, 403])
