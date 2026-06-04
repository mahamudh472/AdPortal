from analysis.models import AnalysisDaily

def save_daily_analytics(org, data, account_id, date):
    for campaign_name, matrix in data.items():
        campaign_id = matrix.get("campaign_id")
        device_breakdown = matrix.get("device_breakdown", {})
        total_performance = matrix.get("total_performance", {})
        spend = total_performance.get("spend", 0.0)
        impressions = total_performance.get("impressions", 0)
        clicks = total_performance.get("clicks", 0)
        ctr = total_performance.get("ctr", 0.0)
        cpc = total_performance.get("cpc", 0.0)
        cpm = total_performance.get("cpm", 0.0)
        conversions = total_performance.get("conversions", 0)
        cpa = total_performance.get("cpa", 0.0)
        roas = total_performance.get("roas", 0.0)
        analysis_entry, created = AnalysisDaily.objects.update_or_create(
            organization=org,
            platform="TIKTOK",
            account_id=account_id,
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            adgroup_id=None,
            date=date,
            defaults={
                "impressions": impressions,
                "clicks": clicks,
                "spend": spend,
                "ctr": ctr,
                "cpc": cpc,
                "cpm": cpm,
                "conversions": conversions,
                "cpa": cpa,
                "roas": roas,
                "device_breakdown": device_breakdown
            }
        )

        
