from apps.main.utils.helper import get_dashboard_data, get_analytics_data

class DashboardService:
    def get_dashboard_data(self, organization, **kwargs):
        return get_dashboard_data(organization.snowflake_id, **kwargs)

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
