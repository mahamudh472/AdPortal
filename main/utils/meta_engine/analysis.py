from facebook_business.adobjects.campaign import Campaign
from django.utils import timezone
from django.db import transaction
from datetime import date
from typing import Optional
from .sync_ad import init_meta_api
from main.models import PlatformCampaign
from analysis.models import AnalysisDaily
from datetime import datetime

@transaction.atomic
def generate_meta_campaign_analysis(
    integration,
    platform_campaign_ids,
    start_date=None,
    end_date=None,
):
    init_meta_api(integration.access_token)

    for campaign_id in platform_campaign_ids:

        platform_campaign = PlatformCampaign.objects.filter(
            integration=integration,
            platform_campaign_id=campaign_id,
            unified_campaign__isnull=False
        ).select_related("unified_campaign").first()

        if not platform_campaign:
            continue

        unified_campaign = platform_campaign.unified_campaign
        campaign = Campaign(campaign_id)

        # -------------------------
        # Fetch Budget
        # -------------------------
        budget_type = None
        budget_amount = None

        try:
            campaign_data = campaign.api_get(
                fields=["daily_budget", "lifetime_budget"]
            )

            if campaign_data.get("daily_budget"):
                budget_type = "DAILY"
                budget_amount = float(campaign_data["daily_budget"]) / 100

            elif campaign_data.get("lifetime_budget"):
                budget_type = "LIFETIME"
                budget_amount = float(campaign_data["lifetime_budget"]) / 100

        except Exception as e:
            pass
        # -------------------------
        # Fetch Insights
        # -------------------------
        params = {
            "level": "campaign",
            "time_increment": 1,
        }

        if start_date and end_date:
            params["time_range"] = {
                "since": start_date.strftime("%Y-%m-%d"),
                "until": end_date.strftime("%Y-%m-%d"),
            }
        else:
            params["date_preset"] = "maximum"

        insights = campaign.get_insights(
            fields=[
                "date_start",
                "impressions",
                "clicks",
                "spend",
                "ctr",
                "cpc",
                "cpm",
                "actions",
                "purchase_roas",
            ],
            params=params,
        )

        for row in insights:

            row_date = datetime.strptime(
                row["date_start"], "%Y-%m-%d"
            ).date()

            conversions = 0
            if row.get("actions"):
                for action in row["actions"]:
                    if action.get("action_type") == "purchase":
                        conversions += int(action.get("value", 0))

            roas = 0
            if row.get("purchase_roas"):
                roas = float(row["purchase_roas"][0].get("value", 0))

            spend = float(row.get("spend", 0))

            obj, created = AnalysisDaily.objects.update_or_create(
                platform=integration.platform,
                account_id=integration.ad_account_id,
                campaign_id=campaign_id,
                adgroup_id=None,
                date=row_date,
                defaults={
                    "organization": integration.organization,
                    "unified_campaign": unified_campaign,
                    "campaign_name": unified_campaign.name,
                    "impressions": int(row.get("impressions", 0)),
                    "clicks": int(row.get("clicks", 0)),
                    "spend": spend,
                    "ctr": float(row.get("ctr", 0)),
                    "cpc": float(row.get("cpc", 0)),
                    "cpm": float(row.get("cpm", 0)),
                    "conversions": conversions,
                    "cpa": (spend / conversions) if conversions > 0 else 0,
                    "roas": roas,
                    "device_breakdown": {},
                    "budget_type": budget_type,
                    "budget_amount": budget_amount,
                },
            )

