"""
Tests for analysis/reporting endpoints:
  GET  /api/v1/analysis/reports/?org_id=
  POST /api/v1/analysis/generate-report/?org_id=
"""
from unittest.mock import patch

from analysis.models import Report
from analysis.tests.base import AnalysisTestBase

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

    @patch("analysis.views.generate_report_task")
    def test_generate_weekly_report_returns_202(self, mock_task):
        mock_task.delay.return_value = None
        res = self.client.post(self._url(), {"report_type": "weekly"}, format="json")
        self.assertEqual(res.status_code, 202)
        self.assertIn("report_id", res.data)
        self.assertEqual(
            Report.objects.filter(organization=self.org, report_type="weekly").count(), 1
        )
        mock_task.delay.assert_called_once()

    @patch("analysis.views.generate_report_task")
    def test_generate_monthly_report_returns_202(self, mock_task):
        mock_task.delay.return_value = None
        res = self.client.post(self._url(), {"report_type": "monthly"}, format="json")
        self.assertEqual(res.status_code, 202)

    @patch("analysis.views.generate_report_task")
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

    @patch("analysis.views.generate_report_task")
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
