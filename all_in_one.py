import sys
import os
from datetime import datetime, timedelta
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.adimage import AdImage
from facebook_business.adobjects.adcreative import AdCreative
from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.user import User


# --- CONFIGURATION (FILL THESE IN) ---
my_app_id = '1391829899306238'           # Found in Settings > Basic
my_app_secret = 'c8c8160e8029e7974984d678d84d71b5'   # Found in Settings > Basic
my_access_token = 'EAATx3Ka8ZAP4BQOJOnHpFdK6lfOTU1cbjZBR3m1vwNY3YqMLd2ZBCNIO1PJe6C2bCLbGKWr4KcO2TfnLL7nkFZAcjiQZB5n1178RHhbJdoFZBB721lLaqdheo9Uk4WA8sZCAI0m0S3SrMiibvB7DfmkAMaE0bZBuSINKbDruaWgCVHwGF9KwBhr6JfWPXs8UsX6vdOSZChuIS' # The token you copied in Step 4


# ⚠️ USE YOUR SANDBOX ID HERE (Must start with act_)
# Do NOT use the account that gave you the payment error.
sandbox_account_id = 'act_1205497834821130' 

# Use the Real Page ID or Test Page ID you found earlier
page_id = '881404995047804' 

# --- INITIALIZATION ---
FacebookAdsApi.init(my_app_id, my_app_secret, my_access_token)

def run_full_flow():
    account = AdAccount(sandbox_account_id)
    print(f"🚀 Starting Full Creation Flow in Sandbox: {sandbox_account_id}")

    # --- 1. CREATE CAMPAIGN ---
    print("\n1️⃣ Creating Campaign...")
    params = {
        'name': 'Sandbox Full Test Campaign',
        'objective': 'OUTCOME_TRAFFIC',
        'status': 'PAUSED',
        'special_ad_categories': [],
        'is_adset_budget_sharing_enabled': False
    }
    campaign = account.create_campaign(params=params)
    campaign_id = campaign['id']
    print(f"✅ Campaign Created: {campaign_id}")

    # --- 2. CREATE AD SET ---
    print("\n2️⃣ Creating Ad Set...")
    start_time = datetime.now() + timedelta(minutes=15)
    adset_params = {
        'name': 'Sandbox AdSet',
        'campaign_id': campaign_id,
        'daily_budget': 100000, # $100.00
        'billing_event': 'IMPRESSIONS',
        'optimization_goal': 'LINK_CLICKS',
        'bid_strategy': 'LOWEST_COST_WITHOUT_CAP',
        'start_time': start_time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'status': 'PAUSED',
        'targeting': {
            'geo_locations': {'countries': ['US']},
            'age_min': 18,
            'age_max': 65,
            # Sandbox usually prefers default targeting, turning automation off to be safe
            'targeting_automation': {'advantage_audience': 0} 
        }
    }
    adset = account.create_ad_set(params=adset_params)
    adset_id = adset['id']
    print(f"✅ Ad Set Created: {adset_id}")

    # --- 3. UPLOAD IMAGE ---
    print("\n3️⃣ Uploading Image...")
    current_dir = os.path.dirname(os.path.abspath(__file__))
    image_path = os.path.join(current_dir, 'ad_image.jpg')
    
    if not os.path.exists(image_path):
        print("❌ Error: ad_image.jpg not found.")
        return

    image = account.create_ad_image(params={'filename': image_path})
    
    if isinstance(image, list):
        image_hash = image[0]['hash']
    else:
        # This matches the <AdImage> output you posted
        image_hash = image['hash']
    # --- FIXED LOGIC END ---
        
    print(f"✅ Image Uploaded: {image_hash}")
    print(f"✅ Image Uploaded: {image_hash}")

    # --- 4. CREATE CREATIVE ---
    print("\n4️⃣ Creating Creative...")
    creative_params = {
        'name': 'Sandbox Creative',
        'object_story_spec': {
            'page_id': page_id,
            'link_data': {
                'image_hash': image_hash,
                'link': 'https://www.google.com',
                'message': 'Sandbox Test Ad Body',
                'name': 'Sandbox Headline',
                'call_to_action': {
                    'type': 'LEARN_MORE',
                    'value': {'link': 'https://www.google.com'}
                }
            }
        }
    }
    creative = account.create_ad_creative(params=creative_params)
    creative_id = creative['id']
    print(f"✅ Creative Created: {creative_id}")

    # --- 5. CREATE AD ---
    print("\n5️⃣ Creating Final Ad...")
    ad_params = {
        'name': 'Sandbox Final Ad',
        'adset_id': adset_id,
        'creative': {'creative_id': creative_id},
        'status': 'PAUSED'
    }
    
    try:
        ad = account.create_ad(params=ad_params)
        print(f"\n🎉 SUCCESS! Sandbox Ad Created ID: {ad['id']}")
        print("You have successfully simulated the entire process without paying!")
    except Exception as e:
        print(f"\n❌ FAILED to create Ad: {e}")

def list_my_accounts():
    try:
        me = User(fbid='me')
        my_accounts = me.get_ad_accounts(fields=['name', 'account_id', 'account_status'])
        
        print(f"Found {len(my_accounts)} Ad Accounts linked to this token:\n")
        
        if len(my_accounts) == 0:
            print("⚠️ No Ad Accounts found. You might need to add your User to the Ad Account in Business Manager.")
        
        for account in my_accounts:
            print(f"Name: {account['name']}")
            print(f"ID for code: act_{account['account_id']}") # Copy this exact string
            print(f"Status: {account['account_status']}")
            print("-" * 30)
            
    except Exception as e:
        print(f"Error: {e}")


if __name__ == '__main__':
    run_full_flow()