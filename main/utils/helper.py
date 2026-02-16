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
    all_analysis_data = AnalysisDaily.objects.filter(organization=organization)
    total_spend = all_analysis_data.aggregate(total_spend=Sum('spend'))['total_spend'] or 0
    impressions = all_analysis_data.aggregate(total_impressions=Sum('impressions'))['total_impressions'] or 0
    click_rate = (all_analysis_data.aggregate(total_clicks=Sum('clicks'))['total_clicks'] or 0) / impressions if impressions > 0 else 0
    roas = (all_analysis_data.aggregate(avg_roas=Sum('roas'))['avg_roas'] or 0) / all_analysis_data.count() if all_analysis_data.exists() else 0
    
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

def get_analytics_data(organization_id: str):
    # Needed fields: Total spend, impressions, click rate, roas for the last 6 months, grouped by month. spend by last month performance by device.
    organization = Organization.objects.get(snowflake_id=organization_id)
    all_analysis_data = AnalysisDaily.objects.filter(organization=organization)
    total_spend = all_analysis_data.aggregate(total_spend=Sum('spend'))['total_spend'] or 0
    impressions = all_analysis_data.aggregate(total_impressions=Sum('impressions'))['total_impressions'] or 0
    click_rate = (all_analysis_data.aggregate(total_clicks=Sum('clicks'))['total_clicks'] or 0) / impressions if impressions > 0 else 0
    roas = (all_analysis_data.aggregate(avg_roas=Sum('roas'))['avg_roas'] or 0) / all_analysis_data.count() if all_analysis_data.exists() else 0
    week_ago = timezone.now() - timedelta(days=7)
    analysis_data = AnalysisDaily.objects.filter(
        organization=organization,
        date__gte=week_ago
    ).order_by('date')
    # last 7 days clicks, conversions and impressions by date as key and values as clicks, conversions and impressions
    last_7_days_data = {}
    for i in range(7):
        date = (timezone.now() - timedelta(days=6-i)).date()
        last_7_days_data[date.strftime('%Y-%m-%d')] = {
            'total_clicks': 0,
            'total_impressions': 0,
            'total_conversions': 0
        }
    
    for item in analysis_data.values('date').annotate(
        total_clicks=Sum('clicks'),
        total_impressions=Sum('impressions'),
        total_conversions=Sum('conversions')
    ):
        date_key = item['date'].strftime('%Y-%m-%d')
        if date_key in last_7_days_data:
            last_7_days_data[date_key] = {
                'total_clicks': item['total_clicks'] or 0,
                'total_impressions': item['total_impressions'] or 0,
                'total_conversions': item['total_conversions'] or 0
            }

    
    
    # performance by device
    device_performance = analysis_data.values('device_breakdown').annotate(
        total_spend=Sum('spend'),
        total_clicks=Sum('clicks'),
        total_impressions=Sum('impressions'),
    )
    

    return {
        'total_spend': total_spend,
        'impressions': impressions,
        'click_rate': click_rate,
        'roas': roas,
        'last_7_days_data': last_7_days_data,
        'device_performance': device_performance
    }

