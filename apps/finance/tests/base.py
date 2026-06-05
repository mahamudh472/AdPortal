"""
Shared base for finance tests.
"""
from apps.accounts.tests.base import AdPortalTestBase
from apps.finance.models import Plan, Subscription, Payment
from django.utils import timezone


class FinanceTestBase(AdPortalTestBase):

    def setUp(self):
        super().setUp()
        self.owner = self.create_user(email="finance_owner@example.com")
        self.org = self.create_organization(self.owner)
        self.org_id = self.org.snowflake_id
        self.authenticate(self.owner)

    def create_plan(self, name="starter", price=29.00, active=True):
        return Plan.objects.create(
            name=name,
            price=price,
            interval="month",
            is_active=active,
        )

    def create_subscription(self, plan, status="active"):
        return Subscription.objects.create(
            organization=self.org,
            plan=plan,
            status=status,
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timezone.timedelta(days=30),
        )

    def create_payment(self, subscription, amount=29.00):
        return Payment.objects.create(
            organization=self.org,
            subscription=subscription,
            amount=amount,
            currency="USD",
            status="paid",
            paid_at=timezone.now(),
        )
