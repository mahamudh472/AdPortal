from django.utils import timezone
from datetime import timedelta
from apps.accounts.models import User
from apps.finance.models import Payment, Subscription, Plan
from apps.main.models import Organization
from apps.admin_dashboard.services.dashboard import get_chart_data
from rest_framework.test import APITestCase
from django.urls import reverse
from decimal import Decimal

class AdminDashboardChartTests(APITestCase):
    def setUp(self):
        # Create an admin user for the API client
        self.admin_user = User.objects.create_user(
            email="admin@example.com",
            password="adminpassword123",
            is_staff=True,
            is_superuser=True
        )
        self.client.force_authenticate(user=self.admin_user)

        # Create regular users for testing user growth
        self.now = timezone.now()
        
        # User registered now
        self.user1 = User.objects.create(email="user1@example.com")
        User.objects.filter(pk=self.user1.pk).update(joined_at=self.now)

        # User registered 2 months ago
        self.user2 = User.objects.create(email="user2@example.com")
        self.two_months_ago = self.now - timedelta(days=60)
        User.objects.filter(pk=self.user2.pk).update(joined_at=self.two_months_ago)

        # Create Plan, Organization, Subscription and Payments for testing revenue
        self.plan = Plan.objects.create(name="starter", price=29.00)
        self.org = Organization.objects.create(name="Test Org", owner=self.user1)
        self.sub = Subscription.objects.create(organization=self.org, plan=self.plan, status="active")

        # Payment 1: Paid now
        Payment.objects.create(
            organization=self.org,
            subscription=self.sub,
            amount=Decimal("100.00"),
            status="paid",
            paid_at=self.now
        )

        # Payment 2: Paid 2 months ago
        Payment.objects.create(
            organization=self.org,
            subscription=self.sub,
            amount=Decimal("150.00"),
            status="paid",
            paid_at=self.two_months_ago
        )

        # Payment 3: Failed (should not count as revenue)
        Payment.objects.create(
            organization=self.org,
            subscription=self.sub,
            amount=Decimal("200.00"),
            status="failed",
            paid_at=self.now
        )

    def test_get_chart_data_service(self):
        """Test the get_chart_data service directly"""
        chart_data = get_chart_data()
        
        # Should return exactly 6 months of data
        self.assertEqual(len(chart_data), 6)

        # Verify key fields present in each month's dictionary
        for data in chart_data:
            self.assertIn("month", data)
            self.assertIn("users", data)
            self.assertIn("revenue", data)

        # The current month should have cumulative user count of at least 3 (admin + user1 + user2)
        current_month_data = chart_data[-1]
        self.assertEqual(current_month_data["users"], 3)
        self.assertEqual(current_month_data["revenue"], 100.0)

    def test_dashboard_api_view(self):
        """Test the dashboard API endpoint returns dynamic chart data and revenue"""
        url = "/api/v1/admin/dashboard/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertIn("chart_data", data)
        self.assertIn("revenue", data)
        
        # Verify revenue structure
        self.assertIn("value", data["revenue"])
        self.assertIn("percentage", data["revenue"])
        self.assertEqual(data["revenue"]["value"], 100.0)
        self.assertIn("trend", data["revenue"])
        self.assertIn("direction", data["revenue"]["trend"])
        self.assertIn("sparkline", data["revenue"]["trend"])
        self.assertEqual(len(data["revenue"]["trend"]["sparkline"]), 6)

        # Verify users structure
        self.assertIn("users", data)
        self.assertIn("value", data["users"])
        self.assertIn("past_month", data["users"])
        self.assertIn("percentage", data["users"])
        self.assertIn("trend", data["users"])
        self.assertIn("direction", data["users"]["trend"])
        self.assertIn("sparkline", data["users"]["trend"])
        self.assertEqual(len(data["users"]["trend"]["sparkline"]), 6)

        # Verify campaigns structure
        self.assertIn("campaings", data)
        self.assertIn("value", data["campaings"])
        self.assertIn("last_month", data["campaings"])
        self.assertIn("percentage", data["campaings"])
        self.assertIn("trend", data["campaings"])
        self.assertIn("direction", data["campaings"]["trend"])
        self.assertIn("sparkline", data["campaings"]["trend"])
        self.assertEqual(len(data["campaings"]["trend"]["sparkline"]), 6)

        # Verify chart_data structure
        self.assertEqual(len(data["chart_data"]), 6)
        self.assertEqual(data["chart_data"][-1]["users"], 3)
        self.assertEqual(data["chart_data"][-1]["revenue"], 100.0)


class AdminReportTests(APITestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            email="admin_reports@example.com",
            password="adminpassword123",
            is_staff=True,
            is_superuser=True
        )
        self.client.force_authenticate(user=self.admin_user)

    def test_generate_report_and_fields(self):
        url = "/api/v1/admin/generate-report/"
        payload = {
            "report_type": "weekly",
            "included_metrics": ["revenue_overview"]
        }
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, 202)
        report_id = res.data["report_id"]

        # Check report list contains the created report with new fields
        list_url = "/api/v1/admin/reports/"
        list_res = self.client.get(list_url)
        self.assertEqual(list_res.status_code, 200)
        results = list_res.data.get("results", list_res.data)
        self.assertTrue(len(results) > 0)
        report_data = results[0]
        self.assertIn("file_size", report_data)
        self.assertIn("download_count", report_data)
        self.assertIn("generated_by", report_data)
        self.assertEqual(str(report_data["generated_by"]), str(self.admin_user.id))

    def test_report_download_count_increment(self):
        from apps.admin_dashboard.models import AdminReport
        report = AdminReport.objects.create(
            name="Test Report",
            report_type="weekly",
            status=AdminReport.Status.COMPLETED,
            download_count=0
        )
        download_url = f"/api/v1/admin/reports/{report.id}/download/"
        res = self.client.post(download_url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["download_count"], 1)

        report.refresh_from_db()
        self.assertEqual(report.download_count, 1)


class AdminStatsTests(APITestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            email="admin_stats@example.com",
            password="adminpassword123",
            is_staff=True,
            is_superuser=True
        )
        self.client.force_authenticate(user=self.admin_user)
        
        # Create user 1: active user, joined now
        self.user1 = User.objects.create(email="user1@example.com", is_active=True, status="active")
        
        # Create user 2: suspended user, joined now
        self.user2 = User.objects.create(email="user2@example.com", is_active=False, status="suspended")
        
        # Create user 3: trial user (owner of a trial organization)
        self.user3 = User.objects.create(email="user3@example.com", is_active=True, status="active")
        
        # Create organizations
        # Org 1: Active, created now
        self.org1 = Organization.objects.create(name="Active Org", owner=self.user1, status="ACTIVE")
        
        # Org 2: Suspended, created now
        self.org2 = Organization.objects.create(name="Suspended Org", owner=self.user2, status="SUSPENDED")
        
        # Org 3: Trial, created now
        self.org3 = Organization.objects.create(name="Trial Org", owner=self.user3, status="TRIAL")

    def test_organization_stats_api(self):
        url = "/api/v1/admin/organizations/stats/"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        
        data = res.json()
        self.assertIn("total_organizations", data)
        self.assertEqual(data["total_organizations"], 7)
        
        # Check active orgs structure and values
        self.assertIn("active_organizations", data)
        self.assertEqual(data["active_organizations"]["value"], 5)
        self.assertEqual(data["active_organizations"]["previous_period"], 0)
        self.assertEqual(data["active_organizations"]["trend_percentage"], "+100%")
        self.assertEqual(data["active_organizations"]["trend_direction"], "up")
        
        # Check suspended orgs structure
        self.assertIn("suspended_organizations", data)
        self.assertEqual(data["suspended_organizations"]["value"], 1)
        
        # Check trial orgs structure
        self.assertIn("trial_organizations", data)
        self.assertEqual(data["trial_organizations"]["value"], 1)

    def test_user_management_stats_api(self):
        url = "/api/v1/admin/user-management/"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        
        data = res.json()
        self.assertIn("total_users", data)
        # 1 admin user + 3 regular users = 4 total users
        self.assertEqual(data["total_users"]["value"], 4)
        
        # Check flat numbers format
        self.assertIn("active_users", data)
        self.assertIn("suspended_users", data)
        self.assertIn("trial_users", data)
        
        # Check specific values
        self.assertEqual(data["active_users"], 3)
        self.assertEqual(data["suspended_users"], 1)
        self.assertEqual(data["trial_users"], 1)

    def test_patch_organization_status(self):
        url = f"/api/v1/admin/organizations/{self.org1.snowflake_id}/"
        payload = {"status": "suspended"}
        res = self.client.patch(url, payload, format="json")
        self.assertEqual(res.status_code, 200)
        
        # Verify response matches
        data = res.json()
        self.assertEqual(data["status"], "SUSPENDED")
        
        # Verify db updated
        self.org1.refresh_from_db()
        self.assertEqual(self.org1.status, "SUSPENDED")

    def test_delete_organization(self):
        url = f"/api/v1/admin/organizations/{self.org1.snowflake_id}/"
        self.assertEqual(self.client.delete(url).status_code, 400)  # confirmation required
        res = self.client.delete(url + f"?confirm={self.org1.snowflake_id}")
        self.assertEqual(res.status_code, 204)
        
        # Verify deleted from DB
        self.assertFalse(Organization.objects.filter(snowflake_id=self.org1.snowflake_id).exists())

    def test_patch_organization_status_active(self):
        # org2 is initially SUSPENDED, patch to active
        url = f"/api/v1/admin/organizations/{self.org2.snowflake_id}/"
        payload = {"status": "active"}
        res = self.client.patch(url, payload, format="json")
        self.assertEqual(res.status_code, 200)
        
        # Verify response matches
        data = res.json()
        self.assertEqual(data["status"], "ACTIVE")
        
        # Verify DB updated
        self.org2.refresh_from_db()
        self.assertEqual(self.org2.status, "ACTIVE")

    def test_organization_list_status_filter(self):
        # Retrieve suspended organizations
        url = "/api/v1/admin/organizations/?status=suspended"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        
        data = res.json()
        self.assertIn("results", data)
        results = data["results"]
        self.assertTrue(len(results) > 0)
        for org in results:
            self.assertEqual(org["status"], "SUSPENDED")
            
        # Retrieve trial organizations
        url = "/api/v1/admin/organizations/?status=trial"
        res = self.client.get(url)
        results = res.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Trial Org")

    def test_finance_overview_api_extensions(self):
        # Create some payments to test sparklines and payment summary
        Payment.objects.create(
            organization=self.org1,
            amount=Decimal("150.00"),
            status="paid",
            paid_at=timezone.now()
        )
        Payment.objects.create(
            organization=self.org1,
            amount=Decimal("50.00"),
            status="failed",
            created_at=timezone.now()
        )
        
        url = "/api/v1/admin/finance/"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("sparklines", data)
        self.assertIn("monthly_revenue", data["sparklines"])
        self.assertIn("mrr_growth", data["sparklines"])
        self.assertIn("total_transactions", data["sparklines"])
        self.assertIn("failed_payments", data["sparklines"])
        self.assertEqual(len(data["sparklines"]["monthly_revenue"]), 6)
        
        self.assertIn("payment_summary", data)
        self.assertIn("successful", data["payment_summary"])
        self.assertIn("failed", data["payment_summary"])
        self.assertIn("refunded", data["payment_summary"])
        self.assertEqual(data["payment_summary"]["successful"]["count"], 1)
        self.assertEqual(data["payment_summary"]["successful"]["total"], 150.0)
        self.assertEqual(data["payment_summary"]["failed"]["count"], 1)

    def test_platform_analysis_api_extensions(self):
        url = "/api/v1/admin/platform-analysis/"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("summary", data)
        self.assertIn("total_new_users", data["summary"])
        self.assertIn("avg_active_users", data["summary"])
        self.assertIn("churned_users", data["summary"])
        self.assertIn("most_used_feature", data["summary"])
        
        self.assertIn("sparkline", data["summary"]["total_new_users"])
        self.assertEqual(len(data["summary"]["total_new_users"]["sparkline"]), 6)

    def test_upcoming_invoices_api(self):
        from apps.finance.models import Invoice
        Invoice.objects.create(
            organization=self.org1,
            amount=Decimal("399.00"),
            due_date=timezone.now().date(),
            plan="Growth",
            status="pending"
        )
        Invoice.objects.create(
            organization=self.org1,
            amount=Decimal("29.00"),
            due_date=timezone.now().date(),
            plan="Starter",
            status="paid"  # should not be returned by upcoming invoices view
        )
        
        url = "/api/v1/admin/invoices/upcoming/"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("results", data)
        self.assertEqual(len(data["results"]), 1)
        inv = data["results"][0]
        self.assertEqual(inv["organization"], "Active Org")
        self.assertEqual(float(inv["amount"]), 399.00)
        self.assertEqual(inv["plan"], "Growth")
        self.assertEqual(inv["status"], "pending")
