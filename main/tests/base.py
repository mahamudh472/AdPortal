"""
Shared base for main-app tests — extends the accounts base.
"""
from accounts.tests.base import AdPortalTestBase
from main.models import AdIntegration, UnifiedCampaign


class MainTestBase(AdPortalTestBase):

    def setUp(self):
        super().setUp()
        self.owner = self.create_user(email="owner@example.com")
        self.org = self.create_organization(self.owner)
        self.org_id = self.org.snowflake_id
        self.authenticate(self.owner)

    def _org_params(self):
        return {"org_id": self.org_id}

    def create_integration(self, platform="META"):
        return AdIntegration.objects.create(
            organization=self.org,
            platform=platform,
            access_token="fake-token-123",
            ad_account_id=f"act_{platform.lower()}_123",
            is_active=True,
        )

    def create_campaign(self, name="Test Campaign", status="DRAFT"):
        return UnifiedCampaign.objects.create(
            organization=self.org,
            name=name,
            status=status,
            objective="TRAFFIC",
        )
