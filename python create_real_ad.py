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
from dotenv import load_dotenv
load_dotenv()

# --- ⚠️ CONFIGURATION (USE REAL IDs) ⚠️ ---
my_app_id = os.getenv('my_app_id')
my_app_secret = os.getenv('my_app_secret')   
my_access_token = os.getenv('my_access_token') 

real_ad_account_id = os.getenv('real_ad_account_id') 
real_page_id = os.getenv('real_page_id')

# --- INITIALIZATION ---
FacebookAdsApi.init(my_app_id, my_app_secret, my_access_token)

def create_production_ad():
    account = AdAccount(real_ad_account_id)
    print(f"🚀 Starting Production Creation in: {real_ad_account_id}")

    # --- 1. CREATE CAMPAIGN ---
    print("\n1️⃣ Creating Campaign (Status: PAUSED)...")
    params = {
        'name': ' production_test_01', # Change name to track it easily
        'objective': 'OUTCOME_TRAFFIC',
        'status': 'PAUSED', # Safe Mode
        'special_ad_categories': [],
        'is_adset_budget_sharing_enabled': False
    }
    campaign = account.create_campaign(params=params)
    campaign_id = campaign['id']
    print(f"✅ Campaign Created: {campaign_id}")

    # --- 2. CREATE AD SET ---
    print("\n2️⃣ Creating Ad Set...")
    # Start time must be at least 15 mins in future
    start_time = datetime.now() + timedelta(minutes=20)
    
    adset_params = {
        'name': 'Production AdSet',
        'campaign_id': campaign_id,
        'daily_budget': 500, # e.g., $5.00 or 500 BDT
        'billing_event': 'IMPRESSIONS',
        'optimization_goal': 'LINK_CLICKS',
        'bid_strategy': 'LOWEST_COST_WITHOUT_CAP',
        'start_time': start_time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'status': 'PAUSED',
        'targeting': {
            'geo_locations': {'countries': ['US']}, # Change to ['BD'] if you want
            'age_min': 18,
            'age_max': 65,
            # We turn off Advantage+ to keep things simple
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
    
    # Handle response format
    if isinstance(image, list):
        image_hash = image[0]['hash']
    else:
        image_hash = image['hash']
        
    print(f"✅ Image Uploaded: {image_hash}")

    # --- 4. CREATE CREATIVE ---
    print("\n4️⃣ Creating Creative...")
    creative_params = {
        'name': 'Production Creative',
        'object_story_spec': {
            'page_id': real_page_id,
            'link_data': {
                'image_hash': image_hash,
                'link': 'https://www.google.com',
                'message': 'This is a real ad created via Python API.',
                'name': 'Headline: Python is working!',
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

    # --- 5. CREATE FINAL AD ---
    print("\n5️⃣ Creating Final Ad...")
    ad_params = {
        'name': 'Final Production Ad',
        'adset_id': adset_id,
        'creative': {'creative_id': creative_id},
        'status': 'PAUSED' # Double safety
    }
    
    try:
        ad = account.create_ad(params=ad_params)
        print(f"\n🎉 CONGRATULATIONS! REAL AD CREATED: {ad['id']}")
        print("Go to Facebook Ads Manager to see it.")
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
    create_production_ad()