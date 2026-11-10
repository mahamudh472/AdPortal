"""
Tests for analysis/reporting endpoints:
  GET  /api/v1/analysis/reports/?org_id=
  POST /api/v1/analysis/generate-report/?org_id=
"""
from unittest.mock import patch

from apps.analysis.models import AnalysisDaily, Report
from apps.analysis.tests.base import AnalysisTestBase

BASE = "/api/v1/analysis"


class ReportListTests(AnalysisTestBase):
    """Tests for GET /api/v1/analysis/reports/"""

    def _url(self):
        return f"{BASE}/reports/"

    def test_list_reports_returns_200(self):
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)

    def test_list_reports_returns_org_reports(self):
        self.create_report("weekly")
        self.create_report("monthly")
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(res.data["count"], 2)

    def test_list_reports_empty_for_new_org(self):
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["count"], 0)

    def test_list_reports_non_member_returns_403(self):
        other = self.create_user(email="rpt_stranger@example.com")
        self.authenticate(other)
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 403)

    def test_list_reports_unauthenticated_returns_401(self):
        self.client.credentials()
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 401)


class GenerateReportTests(AnalysisTestBase):
    """Tests for POST /api/v1/analysis/generate-report/"""

    def _url(self):
        return f"{BASE}/generate-report/?org_id={self.org_id}"

    @patch("apps.analysis.views.generate_report_task")
    def test_generate_weekly_report_returns_202(self, mock_task):
        mock_task.delay.return_value = None
        res = self.client.post(self._url(), {"report_type": "weekly"}, format="json")
        self.assertEqual(res.status_code, 202)
        self.assertIn("report_id", res.data)
        self.assertEqual(
            Report.objects.filter(organization=self.org, report_type="weekly").count(), 1
        )
        mock_task.delay.assert_called_once()

    @patch("apps.analysis.views.generate_report_task")
    def test_generate_monthly_report_returns_202(self, mock_task):
        mock_task.delay.return_value = None
        res = self.client.post(self._url(), {"report_type": "monthly"}, format="json")
        self.assertEqual(res.status_code, 202)

    @patch("apps.analysis.views.generate_report_task")
    def test_generate_custom_report_with_dates_returns_202(self, mock_task):
        mock_task.delay.return_value = None
        res = self.client.post(
            self._url(),
            {"report_type": "custom", "start_date": "2026-01-01", "end_date": "2026-01-31"},
            format="json",
        )
        self.assertEqual(res.status_code, 202)

    def test_generate_custom_report_missing_dates_returns_400(self):
        res = self.client.post(self._url(), {"report_type": "custom"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_generate_custom_report_start_after_end_returns_400(self):
        res = self.client.post(
            self._url(),
            {"report_type": "custom", "start_date": "2026-02-01", "end_date": "2026-01-01"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_generate_report_invalid_date_format_returns_400(self):
        res = self.client.post(
            self._url(),
            {"report_type": "custom", "start_date": "01-01-2026", "end_date": "31-01-2026"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_generate_report_invalid_report_type_returns_400(self):
        res = self.client.post(self._url(), {"report_type": "quarterly"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_generate_report_invalid_platform_returns_400(self):
        res = self.client.post(
            self._url(),
            {"report_type": "weekly", "included_platforms": ["SNAPCHAT"]},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_generate_report_invalid_metric_returns_400(self):
        res = self.client.post(
            self._url(),
            {"report_type": "weekly", "included_metrics": ["likes"]},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    @patch("apps.analysis.views.generate_report_task")
    def test_generate_report_valid_platforms_and_metrics(self, mock_task):
        mock_task.delay.return_value = None
        res = self.client.post(
            self._url(),
            {
                "report_type": "weekly",
                "included_platforms": ["META", "TIKTOK"],
                "included_metrics": ["spend", "clicks", "impressions"],
            },
            format="json",
        )
        self.assertEqual(res.status_code, 202)

    def test_generate_report_non_admin_returns_403(self):
        """Only ADMIN / OWNER can generate reports."""
        member = self.create_user(email="rpt_member@example.com")
        self.add_member(member, self.org, role="MEMBER")
        self.authenticate(member)
        res = self.client.post(self._url(), {"report_type": "weekly"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_generate_report_unauthenticated_returns_401(self):
        self.client.credentials()
        res = self.client.post(self._url(), {"report_type": "weekly"}, format="json")
        self.assertEqual(res.status_code, 401)


class ReportListFilterTests(AnalysisTestBase):
    def test_report_rows_expose_dates_and_status(self):
        self.create_report("weekly")
        res = self.client.get(f"{BASE}/reports/", {"org_id": self.org_id})
        row = res.data["results"][0]
        self.assertIn("start_date", row)
        self.assertIn("end_date", row)
        self.assertEqual(row["status"], "COMPLETED")

    def test_filter_by_report_type(self):
        self.create_report("weekly")
        self.create_report("monthly")
        res = self.client.get(f"{BASE}/reports/", {"org_id": self.org_id, "report_type": "monthly"})
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(res.data["results"][0]["report_type"], "monthly")


class ReportInsightsTests(AnalysisTestBase):
    def test_empty_org_returns_zero_totals(self):
        res = self.client.get(f"{BASE}/report-insights/", {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.data["top_campaign"])
        self.assertEqual(res.data["total_spend"], 0)
        self.assertEqual(res.data["total_impressions"], 0)

    def test_totals_and_top_campaign(self):
        from datetime import date

        from apps.main.models import UnifiedCampaign

        campaign = UnifiedCampaign.objects.create(
            organization=self.org, name="Best", status="ACTIVE", objective="TRAFFIC"
        )
        AnalysisDaily.objects.create(
            organization=self.org, unified_campaign=campaign, platform="META", account_id="a",
            campaign_id="c", adgroup_id="g", date=date.today(), impressions=2000, clicks=100,
            spend=50.0, ctr=5, cpc=0.5, conversions=4, cpa=12.5, roas=3.0,
        )
        res = self.client.get(f"{BASE}/report-insights/", {"org_id": self.org_id})
        self.assertEqual(res.data["top_campaign"], {"name": "Best", "roas": 3.0})
        self.assertEqual(res.data["total_spend"], 50.0)
        self.assertEqual(res.data["total_impressions"], 2000)
        self.assertEqual(res.data["conversion_rate"], 4.0)

    def test_invalid_date_returns_400(self):
        res = self.client.get(f"{BASE}/report-insights/", {"org_id": self.org_id, "start_date": "nope"})
        self.assertEqual(res.status_code, 400)


class ScheduledReportTests(AnalysisTestBase):
    def test_defaults_are_seeded_once(self):
        res = self.client.get(f"{BASE}/scheduled-reports/", {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["count"], 3)
        res = self.client.get(f"{BASE}/scheduled-reports/", {"org_id": self.org_id})
        self.assertEqual(res.data["count"], 3)

    def test_toggle_persists(self):
        first = self.client.get(f"{BASE}/scheduled-reports/", {"org_id": self.org_id}).data["results"][0]
        res = self.client.patch(
            f"{BASE}/scheduled-reports/{first['id']}/?org_id={self.org_id}", {"enabled": False}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        rows = self.client.get(f"{BASE}/scheduled-reports/", {"org_id": self.org_id}).data["results"]
        self.assertFalse(next(r for r in rows if r["id"] == first["id"])["enabled"])

    def test_cannot_toggle_other_orgs_schedule(self):
        first = self.client.get(f"{BASE}/scheduled-reports/", {"org_id": self.org_id}).data["results"][0]
        other_owner = self.create_user(email="sched_other@example.com")
        other_org = self.create_organization(other_owner)
        self.authenticate(other_owner)
        res = self.client.patch(
            f"{BASE}/scheduled-reports/{first['id']}/?org_id={other_org.snowflake_id}",
            {"enabled": False}, format="json",
        )
        self.assertEqual(res.status_code, 404)
