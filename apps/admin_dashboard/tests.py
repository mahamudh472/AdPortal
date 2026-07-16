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
