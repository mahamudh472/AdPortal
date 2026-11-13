"""
Tests for the data that powers the user-dashboard pages:
  GET   /api/v1/main/campaigns/              (trends + sparkline)
  GET   /api/v1/main/campaign/<id>/          (placements)
  GET   /api/v1/main/analytics/              (sparklines, range, insights_summary)
  GET   /api/v1/main/ai-insights/            (summary, metrics, actions)
  GET/PATCH /api/v1/main/ai-optimization/settings/
  GET   /api/v1/main/ai-optimization/history/
  POST  /api/v1/main/ai-optimization/run/
  POST  /api/v1/main/audience-reach-estimate/
  GET   /api/v1/main/team-members/           (joined_at / last_active_at)
  GET   /api/v1/analysis/report-insights/
  GET   /api/v1/analysis/scheduled-reports/
  GET   /api/v1/finance/billing-history/
"""
from datetime import timedelta

from django.utils import timezone

from apps.analysis.models import AnalysisDaily
from apps.main.models import AIInsight, Organization
from apps.main.tests.base import MainTestBase
from apps.main.utils.user_pages import format_trend

BASE = "/api/v1/main"


class UserPagesBase(MainTestBase):
    def add_analysis(self, campaign, days_ago, **overrides):
        values = dict(
            organization=self.org,
            unified_campaign=campaign,
            platform="META",
            account_id="act_1",
            campaign_id=f"c{campaign.id}",
            campaign_name=campaign.name,
            adgroup_id=f"ag{campaign.id}-{days_ago}",
            date=timezone.now().date() - timedelta(days=days_ago),
            impressions=1000,
            clicks=50,
            spend=100.0,
            ctr=5.0,
            cpc=2.0,
            conversions=10,
            cpa=10.0,
            roas=2.0,
        )
        values.update(overrides)
        return AnalysisDaily.objects.create(**values)


class FormatTrendTests(MainTestBase):
    def test_no_data_returns_none(self):
        self.assertIsNone(format_trend(0, 0))

    def test_increase_and_decrease(self):
        self.assertEqual(format_trend(125, 100), "↑ 25.0%")
        self.assertEqual(format_trend(90, 100), "↓ 10.0%")

    def test_new_activity_is_100_percent(self):
        self.assertEqual(format_trend(5, 0), "↑ 100%")


class CampaignListExtrasTests(UserPagesBase):
    def test_trends_and_sparkline_are_computed(self):
        campaign = self.create_campaign("Active One", status="ACTIVE")
        # current 7-day window: 2 days of data, previous window: 1 day with half the conversions
        self.add_analysis(campaign, 0, conversions=20)
        self.add_analysis(campaign, 1, conversions=20)
        self.add_analysis(campaign, 8, conversions=20)

        res = self.client.get(f"{BASE}/campaigns/", {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        row = next(r for r in res.data["results"] if r["id"] == campaign.id)
        self.assertEqual(row["conversions_trend"], "↑ 100.0%")
        self.assertEqual(len(row["sparkline_data"]), 7)
        self.assertEqual(row["sparkline_data"][-1], 50)

    def test_draft_without_data_has_null_trends(self):
        campaign = self.create_campaign("Draft One")
        res = self.client.get(f"{BASE}/campaigns/", {"org_id": self.org_id})
        row = next(r for r in res.data["results"] if r["id"] == campaign.id)
        self.assertIsNone(row["ctr_trend"])
        self.assertIsNone(row["conversions_trend"])
        self.assertIsNone(row["roas_trend"])
        self.assertEqual(row["sparkline_data"], [0] * 7)


class CampaignPlacementsTests(UserPagesBase):
    def test_placements_split_by_spend(self):
        campaign = self.create_campaign("Placement", status="ACTIVE")
        self.add_analysis(campaign, 1, platform="META", spend=75.0, adgroup_id="a")
        self.add_analysis(campaign, 1, platform="GOOGLE", spend=25.0, adgroup_id="b")

        res = self.client.get(f"{BASE}/campaign/{campaign.id}/", {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        placements = {p["platform"]: p for p in res.data["placements"]}
        self.assertEqual(placements["META"]["percent"], 75.0)
        self.assertEqual(placements["GOOGLE"]["percent"], 25.0)

    def test_placements_empty_without_data(self):
        campaign = self.create_campaign("No Data")
        res = self.client.get(f"{BASE}/campaign/{campaign.id}/", {"org_id": self.org_id})
        self.assertEqual(res.data["placements"], [])


class AnalyticsExtrasTests(UserPagesBase):
    def test_sparklines_and_insights_summary(self):
        campaign = self.create_campaign("Analytics", status="ACTIVE")
        self.add_analysis(campaign, 0, platform="META", conversions=5, adgroup_id="m")
        self.add_analysis(campaign, 0, platform="TIKTOK", conversions=30, roas=4.0, adgroup_id="t")

        res = self.client.get(f"{BASE}/analytics/", {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        for key in ("total_spend", "impressions", "click_rate", "conversions"):
            self.assertEqual(len(res.data["top_metrics"][key]["sparkline"]), 6)
        summary = res.data["insights_summary"]
        self.assertEqual(summary["top_performing_platform"]["platform"], "TIKTOK")
        self.assertEqual(summary["most_conversions_platform"]["platform"], "TIKTOK")

    def test_insights_summary_is_null_without_data(self):
        res = self.client.get(f"{BASE}/analytics/", {"org_id": self.org_id})
        self.assertTrue(all(v is None for v in res.data["insights_summary"].values()))

    def test_range_controls_series_length(self):
        res = self.client.get(f"{BASE}/analytics/", {"org_id": self.org_id, "range": "7D"})
        self.assertEqual(len(res.data["monthly_performance"]), 7)
        res = self.client.get(f"{BASE}/analytics/", {"org_id": self.org_id, "range": "30D"})
        self.assertEqual(len(res.data["monthly_performance"]), 30)
        res = self.client.get(f"{BASE}/analytics/", {"org_id": self.org_id, "range": "3M"})
        self.assertEqual(len(res.data["monthly_performance"]), 3)
        res = self.client.get(f"{BASE}/analytics/", {"org_id": self.org_id, "range": "1Y"})
        self.assertEqual(len(res.data["monthly_performance"]), 12)
        res = self.client.get(f"{BASE}/analytics/", {"org_id": self.org_id})
        self.assertEqual(len(res.data["monthly_performance"]), 6)

    def test_device_performance_aggregates_breakdown(self):
        campaign = self.create_campaign("Devices", status="ACTIVE")
        self.add_analysis(
            campaign, 1,
            device_breakdown={"mobile": {"clicks": 10, "impressions": 100}},
        )
        res = self.client.get(f"{BASE}/analytics/", {"org_id": self.org_id})
        mobile = res.data["device_performance"]["mobile"]
        self.assertEqual(mobile["clicks"], 10)
        self.assertEqual(mobile["impressions"], 100)


class AIInsightsExtrasTests(UserPagesBase):
    def test_list_has_summary_and_item_actions(self):
        campaign = self.create_campaign("AI Campaign", status="ACTIVE")
        self.add_analysis(campaign, 1)
        AIInsight.objects.create(
            organization=self.org, campaign=campaign, title="Raise budget",
            description="d", impact="HIGH",
        )
        AIInsight.objects.create(
            organization=self.org, campaign=campaign, title="Tweak copy",
            description="d", impact="MEDIUM",
        )
        res = self.client.get(f"{BASE}/ai-insights/", {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["summary"]["active_insights"], 2)
        self.assertEqual(res.data["summary"]["high_priority"], 1)
        self.assertIn("potential_impact", res.data)
        self.assertIn("last_optimization", res.data)

        by_title = {r["title"]: r for r in res.data["results"]}
        self.assertEqual(by_title["Raise budget"]["action_type"], "apply")
        self.assertEqual(by_title["Tweak copy"]["action_type"], "fix")
        self.assertEqual(by_title["Raise budget"]["campaigns_count"], 1)
        labels = [m["label"] for m in by_title["Raise budget"]["metrics"]]
        self.assertEqual(labels, ["CTR", "CPC"])


class AIOptimizationSettingsTests(UserPagesBase):
    URL = f"{BASE}/ai-optimization/settings/"

    def test_get_creates_defaults(self):
        res = self.client.get(self.URL, {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["auto_optimization"])
        self.assertEqual(res.data["optimization_mode"], "balanced")
        self.assertEqual(res.data["optimization_frequency"], "Daily Optimization")

    def test_patch_persists(self):
        res = self.client.patch(
            f"{self.URL}?org_id={self.org_id}",
            {"auto_optimization": False, "optimization_mode": "aggressive"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        res = self.client.get(self.URL, {"org_id": self.org_id})
        self.assertFalse(res.data["auto_optimization"])
        self.assertEqual(res.data["optimization_mode"], "aggressive")

    def test_patch_rejects_invalid_mode(self):
        res = self.client.patch(
            f"{self.URL}?org_id={self.org_id}", {"optimization_mode": "reckless"}, format="json"
        )
        self.assertEqual(res.status_code, 400)

    def test_non_member_forbidden(self):
        self.authenticate(self.create_user(email="opt_stranger@example.com"))
        res = self.client.get(self.URL, {"org_id": self.org_id})
        self.assertEqual(res.status_code, 403)

    def test_run_records_timestamp(self):
        res = self.client.post(f"{BASE}/ai-optimization/run/?org_id={self.org_id}")
        self.assertEqual(res.status_code, 200)
        self.assertIsNotNone(res.data["last_optimization"])
        res = self.client.get(f"{BASE}/ai-insights/", {"org_id": self.org_id})
        self.assertIsNotNone(res.data["last_optimization"])

    def test_history_empty_without_campaigns(self):
        res = self.client.get(f"{BASE}/ai-optimization/history/", {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["results"], [])

    def test_device_performance_prefers_breakdown_table(self):
        from apps.analysis.models import AnalysisBreakdownDaily

        campaign = self.create_campaign("Breakdown", status="ACTIVE")
        self.add_analysis(campaign, 1)
        AnalysisBreakdownDaily.objects.create(
            organization=self.org,
            unified_campaign=campaign,
            platform="META",
            account_id="act_1",
            campaign_id=f"c{campaign.id}",
            date=timezone.now().date() - timedelta(days=1),
            dimension="device",
            key="mobile",
            impressions=500,
            clicks=25,
            spend=12.5,
            conversions=2,
            currency="USD",
        )
        res = self.client.get(f"{BASE}/analytics/", {"org_id": self.org_id})
        self.assertEqual(res.data["breakdowns"]["device"][0]["key"], "mobile")
        self.assertEqual(res.data["device_performance"]["mobile"]["spend"], 12.5)

    def test_history_uses_applied_optimization_log(self):
        from apps.main.models import AppliedOptimization

        campaign = self.create_campaign("Any")
        AppliedOptimization.objects.create(
            organization=self.org,
            campaign=campaign,
            kind="BUDGET_INCREASE",
            title="Increased daily budget on Any",
            status=AppliedOptimization.Status.APPLIED,
        )
        res = self.client.get(f"{BASE}/ai-optimization/history/", {"org_id": self.org_id})
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(res.data["results"][0]["title"], "Increased daily budget on Any")
        self.assertEqual(res.data["results"][0]["status"], "Applied")


class AudienceReachTests(UserPagesBase):
    URL = f"{BASE}/audience-reach-estimate/"

    def test_estimate_shape(self):
        res = self.client.post(f"{self.URL}?org_id={self.org_id}", {}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["min_label"], "630K")
        self.assertTrue(res.data["is_estimate"])

    def test_narrow_audience_is_smaller(self):
        wide = self.client.post(f"{self.URL}?org_id={self.org_id}", {}, format="json").data
        narrow = self.client.post(
            f"{self.URL}?org_id={self.org_id}", {"min_age": 25, "max_age": 30}, format="json"
        ).data
        self.assertLess(narrow["min_reach"], wide["min_reach"])

    def test_invalid_age_returns_400(self):
        res = self.client.post(f"{self.URL}?org_id={self.org_id}", {"min_age": 5}, format="json")
        self.assertEqual(res.status_code, 400)


class TeamActivityTests(UserPagesBase):
    def test_members_include_joined_and_last_active(self):
        res = self.client.get(f"{BASE}/team-members/", {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        rows = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertTrue(rows)
        self.assertIn("joined_at", rows[0])
        self.assertIn("last_active_at", rows[0])
        self.assertIsNotNone(rows[0]["joined_at"])


class TeamStatsTests(UserPagesBase):
    def test_pending_invitations_counts_open_invites_only(self):
        from apps.main.models import TeamInvitation

        TeamInvitation.objects.create(organization=self.org, email="a@example.com", role="MEMBER")
        expired = TeamInvitation.objects.create(organization=self.org, email="b@example.com", role="MEMBER")
        TeamInvitation.objects.filter(pk=expired.pk).update(created_at=timezone.now() - timedelta(days=8))
        TeamInvitation.objects.create(
            organization=self.org, email="c@example.com", role="MEMBER", status="ACCEPTED"
        )

        res = self.client.get(f"{BASE}/team/", {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["pending_invitations"], 1)
        self.assertEqual(res.data["total_members"], 1)
        self.assertEqual(res.data["inactive_members"], 0)


class ComputedOptimizationTests(UserPagesBase):
    def _campaign_with_metrics(self, name, *, spend, conversions, value, impressions, clicks):
        campaign = self.create_campaign(name, status="ACTIVE")
        for days_ago in (1, 2, 3):
            self.add_analysis(
                campaign, days_ago,
                spend=spend / 3, conversions=conversions / 3,
                conversion_value=value / 3, impressions=impressions // 3,
                clicks=clicks // 3,
                roas=(value / spend) if spend else 0,
                cpa=(spend / conversions) if conversions else 0,
                ctr=(clicks / impressions * 100) if impressions else 0,
                adgroup_id=f"ag-{days_ago}",
            )
        return campaign

    def test_run_queues_ai_and_never_creates_rule_insights(self):
        from unittest.mock import patch

        self._campaign_with_metrics(
            "Good", spend=100, conversions=20, value=500, impressions=10000, clicks=300
        )
        self._campaign_with_metrics(
            "Bad", spend=100, conversions=4, value=40, impressions=10000, clicks=40
        )

        with patch("apps.main.tasks.generate_ai_insights_for_campaign.delay") as queued:
            res = self.client.post(f"{BASE}/ai-optimization/run/?org_id={self.org_id}")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(queued.call_count, 2)
        self.assertEqual(AIInsight.objects.filter(organization=self.org).count(), 0)

    def test_budget_recommendation_is_computed_without_fake_insights(self):
        good = self._campaign_with_metrics(
            "Good", spend=100, conversions=20, value=500, impressions=10000, clicks=300
        )
        self._campaign_with_metrics(
            "Bad", spend=100, conversions=4, value=40, impressions=10000, clicks=40
        )

        dashboard = self.client.get(f"{BASE}/dashboard/", {"org_id": self.org_id})
        self.assertIsNotNone(dashboard.data["budget_recommendation"])
        self.assertEqual(dashboard.data["budget_recommendation"]["campaign_id"], good.id)
        self.assertEqual(AIInsight.objects.filter(organization=self.org).count(), 0)

    def test_potential_impact_uses_stored_deltas(self):
        campaign = self.create_campaign("Impact", status="ACTIVE")
        AIInsight.objects.create(
            organization=self.org, campaign=campaign, title="Scale",
            description="d", impact="HIGH", recommendation_type="BUDGET_INCREASE",
            expected_delta={"conversions": [5, 12], "roas": [4, 8]}, confidence=80,
        )
        res = self.client.get(f"{BASE}/ai-insights/", {"org_id": self.org_id})
        self.assertEqual(res.data["potential_impact"]["conversions"], "+5% to +12%")
        self.assertEqual(res.data["potential_impact"]["roas"], "+4% to +8%")

    def test_summary_counts_applied_optimizations_today(self):
        from apps.main.models import AppliedOptimization

        campaign = self.create_campaign("Applied", status="ACTIVE")
        AppliedOptimization.objects.create(
            organization=self.org,
            campaign=campaign,
            kind="BUDGET_INCREASE",
            title="Applied",
            status=AppliedOptimization.Status.APPLIED,
            measured_impact={"savings": 42.5},
        )
        res = self.client.get(f"{BASE}/ai-insights/", {"org_id": self.org_id})
        self.assertEqual(res.data["summary"]["applied_today"], 1)
        self.assertEqual(res.data["summary"]["est_savings"], 42.5)


class AppliedOptimizationMeasurementTests(UserPagesBase):
    def test_measurement_fills_savings_after_seven_days(self):
        from apps.main.models import AppliedOptimization
        from apps.main.services.optimization import measure_applied_optimizations

        campaign = self.create_campaign("Measured", status="ACTIVE")
        for days_ago in range(15, 8, -1):
            self.add_analysis(campaign, days_ago, spend=100, conversions=5, conversion_value=50)
        for days_ago in range(8, 1, -1):
            self.add_analysis(campaign, days_ago, spend=100, conversions=10, conversion_value=100)

        entry = AppliedOptimization.objects.create(
            organization=self.org,
            campaign=campaign,
            kind="BUDGET_INCREASE",
            title="Measured change",
            status=AppliedOptimization.Status.APPLIED,
        )
        AppliedOptimization.objects.filter(id=entry.id).update(
            created_at=timezone.now() - timedelta(days=8)
        )

        self.assertEqual(measure_applied_optimizations(), 1)
        entry.refresh_from_db()
        self.assertEqual(entry.measured_impact["savings"], 700.0)
        self.assertIn("CPA -50%", entry.measured_impact["summary"])
