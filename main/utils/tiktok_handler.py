import requests
import json
import os
from django.utils import timezone
from datetime import timezone as dt_timezone
from dotenv import load_dotenv
load_dotenv()

from main.models import UnifiedCampaign, PlatformCampaign

# --- CONFIGURATION (SANDBOX) ---
# ⚠️ TikTok Sandbox URL is different from Production!
BASE_URL = "https://sandbox-ads.tiktok.com/open_api/v1.3"
PRODUCTION_URL = "https://ads.tiktok.com/open_api/v1.3"

# PASTE YOUR CREDENTIALS HERE
ACCESS_TOKEN = os.getenv('ACCESS_TOKEN')
ADVERTISER_ID = os.getenv('ADVERTISER_ID')

# Standard Headers for every request
HEADERS = {
    "Access-Token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}

def to_tiktok_datetime(dt):
    """
    Convert a Python datetime to TikTok Ads API format (UTC).
    Output format: YYYY-MM-DD HH:MM:SS
    """
    if dt is None:
        return None

    # Ensure datetime is timezone-aware and in UTC
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, dt_timezone.utc)
    else:
        dt = dt.astimezone(dt_timezone.utc)

    return dt.strftime("%Y-%m-%d %H:%M:%S")

def get_tiktok_adgroup_config(objective):
    # Standard settings for accounts WITHOUT a pixel
    
    if objective == "TRAFFIC":
        return {
            "promotion_type": "WEBSITE",
            "optimization_goal": "CLICK",   # Must be CLICK for Traffic
            "billing_event": "CPC",        # Must be CPC for CLICK
            "bid_type": "BID_TYPE_NO_BID",
            "pacing": "PACING_MODE_SMOOTH",
        }

    if objective == "AWARENESS":
        return {
            "promotion_type": "WEBSITE",
            "optimization_goal": "REACH",   # Must be REACH for Awareness
            "billing_event": "CPM",        # Must be CPM for REACH
            "bid_type": "BID_TYPE_NO_BID",
            "pacing": "PACING_MODE_SMOOTH",
        }

    if objective == "VIDEO_VIEW":
        return {
            "promotion_type": "WEBSITE",
            "optimization_goal": "VIDEO_VIEW", # Must be VIDEO_VIEW
            "billing_event": "CPM",           # Must be CPM for Video Views
            "bid_type": "BID_TYPE_NO_BID",
            "pacing": "PACING_MODE_SMOOTH",
        }

    if objective == "ENGAGEMENT":
        # If campaign is 'COMMUNITY_INTERACTION', use this:
        return {
            "promotion_type": "WEBSITE",
            "optimization_goal": "CLICK",  # Without pixel, optimize for clicks
            "billing_event": "CPC",
            "bid_type": "BID_TYPE_NO_BID",
            "pacing": "PACING_MODE_SMOOTH",
        }

    # If it's anything else, fallback to Traffic settings to prevent crashes
    return {
        "promotion_type": "WEBSITE",
        "optimization_goal": "CLICK",
        "billing_event": "CPC",
        "bid_type": "BID_TYPE_NO_BID",
        "pacing": "PACING_MODE_SMOOTH",
    }

def create_platform_campaign_for_tiktok(campaign, integration, ADVERTISER_ID, ACCESS_TOKEN):
    print(type(campaign))
    platform_campaign = PlatformCampaign.objects.get(unified_campaign=campaign, integration=integration)
    campaign_budget = campaign.campaignbudget_set.filter(platform='TIKTOK').first()
    if platform_campaign.platform_campaign_id:
        print("TikTok Campaign already exists. Skipping creation.")
        return platform_campaign.platform_campaign_id
    
    url = f"{BASE_URL}/campaign/create/"
    # ADVERTISER_ID = integration.ad_account_id
    # ACCESS_TOKEN = integration.access_token
    HEADERS["Access-Token"] = ACCESS_TOKEN
    
    payload = {
        "advertiser_id": ADVERTISER_ID,
        "campaign_name": campaign.name,
        "objective_type": campaign.objective, # Options: TRAFFIC, CONVERSIONS, REACH
        "budget_mode": "BUDGET_MODE_DAY" if campaign_budget.budget_type == 'DAILY' else "BUDGET_MODE_TOTAL",
        "budget": campaign_budget.daily_budget_minor, # Minimum is usually 50 in Sandbox
    }
    
    res = requests.post(url, headers=HEADERS, json=payload)
    data = res.json()
    
    if data['code'] != 0:
        print(f"❌ Campaign Failed: {data['message']}")
        return
        
    campaign_id = data['data']['campaign_id']
    platform_campaign.platform_campaign_id = campaign_id
    platform_campaign.save()
    print(f"✅ Campaign Created: {campaign_id}")

    return campaign_id
    

def create_ad_group_for_tiktok(campaign_id):
    url = f"{BASE_URL}/adgroup/create/"
    print(campaign_id)
    platform_campaign = PlatformCampaign.objects.get(platform_campaign_id=campaign_id)
    adgroup = platform_campaign.ad_groups.first()
    # Ad Group requires stricter validation than Meta
    payload = {
        "advertiser_id": ADVERTISER_ID,
        "campaign_id": campaign_id,
        "adgroup_name": adgroup.name,
        "placement_type": "PLACEMENT_TYPE_NORMAL",
        "placements": ["PLACEMENT_TIKTOK"],
        "location_ids": ['6252001'],
        "budget_mode": "BUDGET_MODE_DAY",
        "budget": 20.0,
        "schedule_type": "SCHEDULE_START_END",
        "schedule_start_time": to_tiktok_datetime(adgroup.start_time),
        "schedule_end_time": to_tiktok_datetime(adgroup.end_time),
    }
    config = get_tiktok_adgroup_config(platform_campaign.unified_campaign.objective)
    payload.update(config)
    
    res = requests.post(url, headers=HEADERS, json=payload)
    data = res.json()
    
    if data['code'] != 0:
        print(f"❌ Ad Group Failed: {data['message']}")
        return

    adgroup_id = data['data']['adgroup_id']
    adgroup.platform_adgroup_id = adgroup_id
    adgroup.save()
    print(f"✅ Ad Group Created: {adgroup_id}")
    return adgroup_id

def upload_tiktok_video(campaign, integration):
    pass

def create_tiktok_ad_creative(campaign, integration):
    pass

def create_full_ad_for_tiktok(campaign, integration):

    # TODO: Need to change to the actual values from campaign and integration
    campaign_id = create_platform_campaign_for_tiktok(campaign, integration, integration.ad_account_id, integration.access_token)
    adgroup_id = create_ad_group_for_tiktok(campaign_id)

def create_tiktok_ad_flow():
    print(f"🚀 Starting TikTok Sandbox Flow for Advertiser: {ADVERTISER_ID}")

    # --- 1. CREATE CAMPAIGN ---
    print("\n1️⃣ Creating Campaign...")
    url = f"{BASE_URL}/campaign/create/"
    payload = {
        "advertiser_id": ADVERTISER_ID,
        "campaign_name": "Python Sandbox Campaign 2025-12-20 6",
        "objective_type": "REACH", # Options: TRAFFIC, CONVERSIONS, REACH
        "budget_mode": "BUDGET_MODE_DAY",
        "budget": 50.0, # Minimum is usually 50 in Sandbox
    }
    
    res = requests.post(url, headers=HEADERS, json=payload)
    data = res.json()
    
    if data['code'] != 0:
        print(f"❌ Campaign Failed: {data['message']}")
        return
        
    campaign_id = data['data']['campaign_id']
    print(f"✅ Campaign Created: {campaign_id}")
    # campaign_id = "1851326442807426"  # Use existing campaign for testing
    # --- 2. CREATE AD GROUP (Targeting) ---
    print("\n2️⃣ Creating Ad Group...")
    url = f"{BASE_URL}/adgroup/create/"
    
    # Ad Group requires stricter validation than Meta
    payload = {
        "advertiser_id": ADVERTISER_ID,
        "campaign_id": campaign_id,
        "adgroup_name": "Python AdGroup US",
        "placement_type": "PLACEMENT_TYPE_NORMAL", # Only show on TikTok app
        "placements": ["PLACEMENT_TIKTOK"],
        "location_ids": ['6252001'],  # Sandbox usually supports 'US' or 'JP'
        "budget_mode": "BUDGET_MODE_DAY",
        "budget": 20.0,
        "schedule_type": "SCHEDULE_START_END",
        "schedule_start_time": "2025-12-20 00:00:00", # Future date
        "schedule_end_time": "2025-12-30 00:00:00",
        "billing_event": "CPC",
        "bid_type": "BID_TYPE_NO_BID", # Lowest Cost strategy
        "optimization_goal": "CLICK",
        "promotion_type": "WEBSITE", 
    }
    
    res = requests.post(url, headers=HEADERS, json=payload)
    data = res.json()
    
    if data['code'] != 0:
        print(f"❌ Ad Group Failed: {data['message']}")
        return

    adgroup_id = data['data']['adgroup_id']
    print(f"✅ Ad Group Created: {adgroup_id}")

    # --- 3. UPLOAD VIDEO (The Hard Part) ---
    print("\n3️⃣ Uploading Video...")
    # NOTE: You must have a video file named 'ad_video.mp4' in this folder
    video_path = "ad_video.mp4" 
    
    if not os.path.exists(video_path):
        print("❌ Error: 'ad_video.mp4' not found. Please add a video file.")
        return

    # Step A: Initialize Upload to get a Signature
    url = f"{BASE_URL}/file/video/ad/upload/"
    
    # We send the file binary logic differently here
    with open(video_path, 'rb') as f:
        files = {
            'min_picture': ('ad_video.mp4', f, 'video/mp4') # 'min_picture' is weird name but required
        }
        data_payload = {
            "advertiser_id": ADVERTISER_ID,
            "upload_type": "UPLOAD_BY_FILE",
        }
        
        # Requests library handles multipart/form-data automatically if we pass 'files'
        # We DO NOT send JSON content-type here
        upload_headers = {"Access-Token": ACCESS_TOKEN} 
        
        res = requests.post(url, headers=upload_headers, data=data_payload, files=files)
        data = res.json()

    if data['code'] != 0:
        print(f"❌ Video Upload Failed: {data['message']}")
        return

    video_id = data['data']['video_id']
    print(f"✅ Video Uploaded. ID: {video_id}")

    # --- 4. CREATE AD (Creative) ---
    print("\n4️⃣ Creating Final Ad...")
    url = f"{BASE_URL}/ad/create/"
    
    payload = {
        "advertiser_id": ADVERTISER_ID,
        "adgroup_id": adgroup_id,
        "ad_name": "Python Final Ad",
        "creatives": [
            {
                "ad_format": "SINGLE_VIDEO",
                "video_id": video_id,
                "ad_text": "This is a test ad from Python!",
                "call_to_action": "LEARN_MORE",
                "landing_page_url": "https://www.google.com",
                # TikTok requires a profile image and name usually, 
                # but in Sandbox it might use defaults.
                "display_name": "Python Ad Portal"
            }
        ]
    }
    
    res = requests.post(url, headers=HEADERS, json=payload)
    data = res.json()
    
    if data['code'] != 0:
        print(f"❌ Ad Creation Failed: {data['message']}")
        print(data) # Print full error for debugging
        return

    ad_id = data['data']['ad_ids'][0]
    print(f"\n🎉 SUCCESS! TikTok Ad Created. ID: {ad_id}")

def get_campaigns():
    url = f"{BASE_URL}/campaign/get/"
    print(ADVERTISER_ID)
    payload = {
        "advertiser_id": ADVERTISER_ID
    }
    
    res = requests.get(url, headers=HEADERS, params=payload)
    data = res.json()
    with open('tiktok_campaigns.json', 'w') as f:
        json.dump(data, f, indent=4)
    
    if data['code'] != 0:
        print(f"❌ Get Campaigns Failed: {data['message']}")
        return
    
    campaigns = data['data']['list']
    print("\n📋 Current Campaigns:")
    for campaign in campaigns:
        print(f"- ID: {campaign['campaign_id']}, Name: {campaign['campaign_name']}, Objective: {campaign['objective_type']}")
        print(campaign)

def get_single_campaign(campaign_id):
    url = f"{BASE_URL}/campaign/get/"
    payload = {
        "advertiser_id": ADVERTISER_ID,
        "campaign_ids": [campaign_id]
    }
    
    res = requests.get(url, headers=HEADERS, params=payload)
    data = res.json()
    
    if data['code'] != 0:
        print(f"❌ Get Single Campaign Failed: {data['message']}")
        return
    
    campaign = data['data']['list'][0]
    print(f"\n📋 Campaign Details for ID {campaign_id}:")
    print(json.dumps(campaign, indent=4))

def get_analytics(ACCESS_TOKEN=None, ADVERTISER_ID=None):
    url = f"{PRODUCTION_URL}/report/integrated/get/"
    payload = {
        "advertiser_id": ADVERTISER_ID,
        "dimensions": json.dumps(["campaign_id"]), 
        "metrics": json.dumps(["spend", "impressions", "clicks", "cpc", "ctr"]) ,
        "report_type": "BASIC",
        "start_date": "2025-12-01",
        "end_date": "2025-12-20",
        "data_level": "AUCTION_CAMPAIGN",
        "page": 1,
        "page_size": 50
    }
    HEADERS["Access-Token"] = ACCESS_TOKEN
    
    res = requests.get(url, headers=HEADERS, params=payload)

    print("Response Status Code:", res.status_code)
    print("Response Content:", res.text)

    data = res.json()
    
    if data['code'] != 0:
        print(f"❌ Get Analytics Failed: {data['message']}")
        return f"❌ Get Analytics Failed: {data['message']}"
    
    reports = data['data']['list']
    print("\n📊 Analytics Report:")
    for report in reports:
        print(report)
    return reports

if __name__ == '__main__':
    # create_tiktok_ad_flow()
    # get_campaigns()
    # get_single_campaign("7582640422065864711")
    get_analytics()