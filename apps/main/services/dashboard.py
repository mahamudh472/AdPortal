from rest_framework.exceptions import ValidationError
from apps.main.models import Organization, UnifiedCampaign
from apps.main.utils.helper import get_dashboard_data, get_analytics_data

class DashboardService:
    def get_dashboard_data(self, organization):
        from apps.main.models import AIInsight
        # Create some dummy AI insights if there are none for testing purposes
        test_campaign = UnifiedCampaign.objects.filter(organization=organization).first()
        if not organization.ai_insights.exists() and test_campaign:
            AIInsight.objects.create(
                organization=organization,
                campaign=test_campaign,
                title="Test Insight 1",
                description="This is a test insight.",
                impact="HIGH"
            )
            AIInsight.objects.create(
                organization=organization,
                campaign=test_campaign,
                title="Test Insight 2",
                description="This is another test insight.",
                impact="MEDIUM"
            )
        
        return get_dashboard_data(organization.snowflake_id)

    def get_analytics_data(self, snowflake_id):
        return get_analytics_data(snowflake_id)

    def get_integration_status(self, organization):
        integrations = []
        platforms = ['META', 'GOOGLE', 'TIKTOK']
        for platform in platforms:
            integration = organization.integrations.filter(platform=platform).first()
            if integration:
                integrations.append({
                    'platform': platform,
                    'status': True,
                    'created_at': integration.created_at
                })
            else:
                integrations.append({
                    'platform': platform,
                    'status': False,
                    'created_at': None
                })
        return integrations
