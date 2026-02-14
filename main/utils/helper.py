from django.db.models import Sum
from django.utils import timezone
from datetime import timedelta
from main.models import Organization, Platform, UnifiedCampaign
from analysis.models import AnalysisDaily
from main.serializers import SimpleCampaignSerializer, AIInsightSerializer

def get_dashboard_data(organization_id: str):
    organization = Organization.objects.get(snowflake_id=organization_id)
    # Required fieklds: total spend, impressions, click rate, roas
    # Required for matrics: Sepend overview(Meta, Google, TikTok), AI Insigts list, Recent campaigns list.
    
    six_moths_ago = timezone.now() - timedelta(days=180)
    analysis_data = AnalysisDaily.objects.filter(
        organization=organization,
        date__gte=six_moths_ago
    ).annotate(
        total_spend=Sum('spend'),
        ).order_by('platform')
    platforms = Platform.choices
    platform_values = [platform[0] for platform in platforms]

    result = {}
    months = []
    current_date = timezone.now().date()
    for i in range(5, -1, -1):
        month = (current_date - timedelta(days=i*30)).strftime('%b')
        months.append(month)
    for month in months:
        result[month] = {platform: 0 for platform in platform_values}

    for item in analysis_data:
        month = item.date.strftime('%b')
        if month in result:
            result[month][item.platform] += item.total_spend
    # TODO: Implement the logic to calculate total spend, impressions, click rate, and ROAS based on the organization's campaigns and ad data.
    total_spend = analysis_data.aggregate(total_spend=Sum('spend'))['total_spend'] or 0
    impressions = analysis_data.aggregate(total_impressions=Sum('impressions'))['total_impressions'] or 0
    click_rate = analysis_data.aggregate(total_clicks=Sum('clicks'))['total_clicks'] or 0
    roas = analysis_data.aggregate(total_roas=Sum('roas'))['total_roas'] or 0
    
    recent_campaigns = UnifiedCampaign.objects.filter(organization=organization).order_by('-created_at')[:5]
    ai_insights = AIInsightSerializer(organization.ai_insights.order_by('-created_at')[:5], many=True).data
    
    return {
        'total_spend': total_spend,
        'impressions': impressions,
        'click_rate': click_rate,
        'roas': roas,
        'spend_overview': result,
        'ai_insights': ai_insights,  
        'recent_campaigns': SimpleCampaignSerializer(recent_campaigns, many=True).data
    }

