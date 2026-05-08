import os
import django
import requests
from django.conf import settings

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AdPortal.settings")
django.setup()

# Settings
manager_id = str(getattr(settings, "GOOGLE_ADS_MANAGER_ID", "")).replace("-", "")
test_manager_id = str(getattr(settings, "GOOGLE_ADS_TEST_MANAGER_ID", "123456789")).replace("-", "")
use_test_account = getattr(settings, "GOOGLE_ADS_USE_TEST_ACCOUNT", False)
access_token = getattr(settings, "GOOGLE_ADS_ACCESS_TOKEN", None)
refresh_token = getattr(settings, "GOOGLE_ADS_REFRESH_TOKEN", None)
developer_token = getattr(settings, "GOOGLE_ADS_DEVELOPER_TOKEN", None)
google_client_id = getattr(settings, "GOOGLE_CLIENT_ID", None)
google_client_secret = getattr(settings, "GOOGLE_CLIENT_SECRET", None)

# Use test manager ID if enabled
if use_test_account:
    manager_id = test_manager_id
    print(f"🧪 Using TEST account mode with manager ID: {manager_id}")
else:
    print(f"📊 Using PRODUCTION account mode with manager ID: {manager_id}")

print(f"📋 Debug: Manager ID: {manager_id}")
print(f"📋 Debug: Has access token: {bool(access_token)}")
print(f"📋 Debug: Has refresh token: {bool(refresh_token)}")
print(f"📋 Debug: Has developer token: {bool(developer_token)}")
print(f"📋 Debug: Has Google Client ID: {bool(google_client_id)}")
print(f"📋 Debug: Has Google Client Secret: {bool(google_client_secret)}")
print()

GOOGLE_ADS_API_VERSION = (
    str(getattr(settings, "GOOGLE_ADS_API_VERSION", "v18"))
    .strip()
    .strip('"')
    .strip("'")
)

if not GOOGLE_ADS_API_VERSION.startswith("v"):
    GOOGLE_ADS_API_VERSION = f"v{GOOGLE_ADS_API_VERSION}"

GOOGLE_ADS_BASE_URL = (
    f"https://googleads.googleapis.com/{GOOGLE_ADS_API_VERSION}"
)

# Validate required values
if not manager_id:
    raise Exception("GOOGLE_ADS_MANAGER_ID missing")

if not access_token:
    raise Exception("GOOGLE_ADS_ACCESS_TOKEN missing")

if not developer_token:
    raise Exception("GOOGLE_ADS_DEVELOPER_TOKEN missing")

# Function to refresh OAuth access token
def refresh_access_token():
    """Refresh Google OAuth access token using refresh token"""
    global access_token
    
    if not refresh_token:
        print("⚠️  Warning: GOOGLE_ADS_REFRESH_TOKEN not set. Using existing access token.")
        return access_token
    
    if not google_client_id or not google_client_secret:
        print("⚠️  Warning: Google credentials missing. Cannot refresh token.")
        return access_token
    
    try:
        token_url = "https://oauth2.googleapis.com/token"
        
        payload = {
            "client_id": google_client_id,
            "client_secret": google_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        
        response = requests.post(token_url, data=payload)
        
        if response.status_code == 200:
            data = response.json()
            new_access_token = data.get("access_token")
            
            if new_access_token:
                access_token = new_access_token
                print("✅ Access token refreshed successfully")
                return access_token
            else:
                print("⚠️  Failed to extract new access token from response")
                return access_token
        else:
            print(f"⚠️  Token refresh failed with status {response.status_code}")
            print(f"Response: {response.text}")
            return access_token
    
    except Exception as e:
        print(f"⚠️  Error refreshing token: {str(e)}")
        return access_token

# Refresh access token if refresh token is available
if refresh_token:
    print("🔄 Attempting to refresh access token...")
    access_token = refresh_access_token()
else:
    print("⚠️  No refresh token available, using existing access token")
print()

# Endpoint
url = (
    f"{GOOGLE_ADS_BASE_URL}/customers/"
    f"{manager_id}:createCustomerClient"
)

print(f"Request URL: {url}")

# Payload
payload = {
    "customerClient": {
        "descriptiveName": "AdPortal Test Account",
        "currencyCode": "USD",
        "timeZone": "America/New_York",
    }
}

# Headers
headers = {
    "Authorization": f"Bearer {access_token}",
    "developer-token": developer_token,
    "login-customer-id": manager_id,
    "Content-Type": "application/json",
}

# Request
response = requests.post(
    url,
    json=payload,
    headers=headers,
)

print("\nStatus Code:")
print(response.status_code)

print("\nResponse Headers:")
print(response.headers)

print("\nRaw Response:")
print(response.text)

# Try parsing JSON
try:
    data = response.json()

    print("\nParsed JSON:")
    print(data)

    # Success response
    if response.status_code in [200, 201]:
        resource_name = data.get("resourceName")

        print("\n✅ Test account created successfully!")
        print(f"Resource Name: {resource_name}")

        # Extract customer ID
        if resource_name:
            customer_id = resource_name.split("/")[-1]

            print(f"Customer ID: {customer_id}")

            print(
                f"\nGoogle Ads URL:\n"
                f"https://ads.google.com/aw/accounts?ocid={customer_id}"
            )

    else:
        print("\n❌ Failed to create test account")

        error = data.get("error", {})

        print("Error Code:", error.get("code"))
        print("Error Message:", error.get("message"))
        print("Error Status:", error.get("status"))

        if "details" in error:
            print("\nError Details:")
            for detail in error["details"]:
                print(detail)

except Exception as e:
    print("\n❌ Could not parse response JSON")
    print(str(e))