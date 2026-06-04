"""
Shared base for analysis tests.
"""
from accounts.tests.base import AdPortalTestBase
from analysis.models import Report


class AnalysisTestBase(AdPortalTestBase):

    def setUp(self):
        super().setUp()
        self.owner = self.create_user(email="analysis_owner@example.com")
        self.org = self.create_organization(self.owner)
        self.org_id = self.org.snowflake_id
        self.create_subscription(self.org)
        self.authenticate(self.owner)

    def create_report(self, report_type="weekly", status=Report.Status.COMPLETED):
        from datetime import date, timedelta
        end = date.today()
        start = end - timedelta(days=7)
        return Report.objects.create(
            organization=self.org,
            name="Test Report",
            report_type=report_type,
            status=status,
            start_date=start,
            end_date=end,
        )
