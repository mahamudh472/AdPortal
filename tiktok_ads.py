import requests
import json
import os
from dotenv import load_dotenv
load_dotenv()

# --- CONFIGURATION (SANDBOX) ---
# ⚠️ TikTok Sandbox URL is different from Production!
BASE_URL = "https://sandbox-ads.tiktok.com/open_api/v1.3"

# PASTE YOUR CREDENTIALS HERE
ACCESS_TOKEN = os.getenv('ACCESS_TOKEN')
ADVERTISER_ID = os.getenv('ADVERTISER_ID')

# Standard Headers for every request
HEADERS = {
    "Access-Token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}

def create_tiktok_ad_flow():
    print(f"🚀 Starting TikTok Sandbox Flow for Advertiser: {ADVERTISER_ID}")

    # --- 1. CREATE CAMPAIGN ---
    print("\n1️⃣ Creating Campaign...")
    url = f"{BASE_URL}/campaign/create/"
    payload = {
        "advertiser_id": ADVERTISER_ID,
        "campaign_name": "Python Sandbox Campaign 2025-12-20 4",
        "objective_type": "TRAFFIC", # Options: TRAFFIC, CONVERSIONS, REACH
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

    # --- 2. CREATE AD GROUP (Targeting) ---
    print("\n2️⃣ Creating Ad Group...")
    url = f"{BASE_URL}/adgroup/create/"
    
    # Ad Group requires stricter validation than Meta
    payload = {
        "advertiser_id": ADVERTISER_ID,
        "campaign_id": campaign_id,
        "adgroup_name": "Python AdGroup US",
        "PLACEMENT_TYPE_NORMAL": "PLACEMENT_TYPE_NORMAL", # Only show on TikTok app
        "placements": ["PLACEMENT_TIKTOK"],
        "location_ids": ["2336152"],  # Sandbox usually supports 'US' or 'JP'
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

if __name__ == '__main__':
    create_tiktok_ad_flow()