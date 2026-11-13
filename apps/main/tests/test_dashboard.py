"""
Tests for dashboard/analytics/integration endpoints:
  GET /api/v1/main/dashboard/?org_id=
  GET /api/v1/main/analytics/?org_id=
  GET /api/v1/main/integrations-status/?org_id=
"""
from apps.main.tests.base import MainTestBase


class DashboardTests(MainTestBase):
    """Tests for GET /api/v1/main/dashboard/"""

    def _url(self):
        return "/api/v1/main/dashboard/"

    def test_dashboard_returns_200(self):
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        # Verify dynamic dashboard structure
        self.assertIn("platform_cards", res.data)
        self.assertIn("overview_metrics", res.data)
        self.assertIn("chart_data", res.data)
        self.assertIn("top_campaigns", res.data)
        self.assertIn("ai_insights", res.data)
        self.assertIn("budget_recommendation", res.data)
        self.assertIn("date_range", res.data)
        self.assertEqual(len(res.data["platform_cards"]), 5)
        self.assertEqual(len(res.data["overview_metrics"]), 5)

    def test_dashboard_date_filter_returns_200(self):
        res = self.client.get(self._url(), {
            "org_id": self.org_id,
            "time_range": "last_7_days"
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["date_range"]["selected"], "last_7_days")

    def test_apply_budget_recommendation(self):
        url = "/api/v1/main/apply-budget-recommendation/"
        res = self.client.post(f"{url}?org_id={self.org_id}", {"increase_amount": 50})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "success")

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


from datetime import timedelta

from django.utils import timezone

from apps.analysis.models import AnalysisBreakdownDaily, AnalysisDaily
from apps.main.models import AppliedOptimization, CampaignBudget


class RealDashboardDataTests(MainTestBase):
    def _add_analysis(self, campaign, days_ago=0, **overrides):
        values = dict(
            organization=self.org,
            unified_campaign=campaign,
            platform="META",
            account_id="act_1",
            campaign_id=f"c{campaign.id}",
            campaign_name=campaign.name,
            adgroup_id=None,
            date=timezone.now().date() - timedelta(days=days_ago),
            impressions=1000,
            clicks=50,
            spend=100.0,
            ctr=5.0,
            cpc=2.0,
            conversions=10,
            cpa=10.0,
            roas=2.0,
            conversion_value=200.0,
            currency="USD",
        )
        values.update(overrides)
        return AnalysisDaily.objects.create(**values)

    def _add_breakdown(self, campaign, key, days_ago=0, **overrides):
        values = dict(
            organization=self.org,
            unified_campaign=campaign,
            platform="META",
            account_id="act_1",
            campaign_id=f"c{campaign.id}",
            date=timezone.now().date() - timedelta(days=days_ago),
            dimension="publisher_platform",
            key=key,
            impressions=1000,
            clicks=50,
            spend=100.0,
            conversions=10,
            conversion_value=200.0,
            currency="USD",
        )
        values.update(overrides)
        return AnalysisBreakdownDaily.objects.create(**values)

    def test_empty_dashboard_returns_no_demo_values(self):
        res = self.client.get("/api/v1/main/dashboard/", {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["has_data"])
        self.assertEqual(res.data["top_campaigns"], [])
        self.assertEqual(res.data["ai_insights"], [])
        self.assertIsNone(res.data["budget_recommendation"])
        self.assertEqual(res.data["total_spend"], 0)
        self.assertTrue(all(card["spend"] == 0 for card in res.data["platform_cards"]))

    def test_publisher_breakdown_drives_facebook_and_instagram(self):
        campaign = self.create_campaign("Meta split", status="ACTIVE")
        self._add_analysis(campaign, spend=100.0)
        self._add_breakdown(campaign, "facebook", spend=70.0)
        self._add_breakdown(campaign, "instagram", spend=30.0)

        res = self.client.get("/api/v1/main/dashboard/", {"org_id": self.org_id})
        cards = {card["platform"]: card for card in res.data["platform_cards"]}
        self.assertEqual(cards["facebook"]["spend"], 70.0)
        self.assertEqual(cards["instagram"]["spend"], 30.0)
        self.assertEqual(cards["total"]["spend"], 100.0)

    def test_change_is_null_when_previous_period_is_empty(self):
        campaign = self.create_campaign("New", status="ACTIVE")
        self._add_analysis(campaign)

        res = self.client.get("/api/v1/main/dashboard/", {"org_id": self.org_id})
        total = next(c for c in res.data["platform_cards"] if c["platform"] == "total")
        self.assertIsNone(total["change_percent"])
        self.assertEqual(total["delta"], "—")

    def test_all_time_starts_at_first_analytics_row(self):
        campaign = self.create_campaign("History", status="ACTIVE")
        self._add_analysis(campaign, days_ago=100)
        self._add_analysis(campaign, days_ago=0, adgroup_id="today")

        res = self.client.get(
            "/api/v1/main/dashboard/", {"org_id": self.org_id, "time_range": "all_time"}
        )
        expected = (timezone.now().date() - timedelta(days=100)).isoformat()
        self.assertEqual(res.data["date_range"]["start_date"], expected)

    def test_currency_comes_from_integration(self):
        integration = self.create_integration("META")
        integration.currency = "EUR"
        integration.save(update_fields=["currency"])
        campaign = self.create_campaign("Euro", status="ACTIVE")
        self._add_analysis(campaign, currency="EUR", spend=10.0)

        res = self.client.get("/api/v1/main/dashboard/", {"org_id": self.org_id})
        self.assertEqual(res.data["currency"], "EUR")
        self.assertIn("€", res.data["platform_cards"][-1]["formatted_spend"])

    def test_unsynced_integration_is_reported(self):
        self.create_integration("GOOGLE")
        res = self.client.get("/api/v1/main/dashboard/", {"org_id": self.org_id})
        partial = {p["platform"]: p for p in res.data["partial_platforms"]}
        self.assertEqual(partial["GOOGLE"]["reason"], "not_synced")

    def test_apply_budget_records_optimization_and_updates_local_budget(self):
        campaign = self.create_campaign("Budget", status="ACTIVE")
        CampaignBudget.objects.create(
            campaign=campaign,
            platform="META",
            budget_type="DAILY",
            daily_budget_minor=10000,
            start_date=timezone.now().date(),
        )
        res = self.client.post(
            f"/api/v1/main/apply-budget-recommendation/?org_id={self.org_id}",
            {"campaign_id": campaign.id, "increase_amount": 50},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["previous_daily_budget"], 100.0)
        self.assertEqual(res.data["new_daily_budget"], 150.0)
        entry = AppliedOptimization.objects.get(id=res.data["optimization_id"])
        self.assertEqual(entry.status, AppliedOptimization.Status.APPLIED)
        self.assertEqual(entry.after["daily_budget"], 150.0)
