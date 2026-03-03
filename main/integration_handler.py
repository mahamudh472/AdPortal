from datetime import timedelta
from accounts.permissions import IsOrganizationMember, IsRegularPlatformUser
from rest_framework.views import APIView
from rest_framework.response import Response
from urllib.parse import urlencode
from django.conf import settings
import requests
from django.utils.timezone import now
from accounts.models import User
from main.mixins import RequiredOrganizationIDMixin
from main.models import AdIntegration, Platform, Organization
from rest_framework import status
from main.mixins import RequiredOrganizationIDMixin
from django.shortcuts import redirect

from main.utils.google_oauth import generate_oauth_state, validate_oauth_state

def fetch_tiktok_ads_account(organization):
    ad_profile = AdIntegration.objects.filter(organization=organization, platform=Platform.TIKTOK)
    if ad_profile.exists():
        access_token = ad_profile.first().access_token
        advertisers = requests.get(
            "https://business-api.tiktok.com/open_api/v1.3/oauth2/advertiser/get/",
            headers={"Access-Token": access_token},
            params={"app_id": settings.TIKTOK_APP_ID, 'secret': settings.TIKTOK_APP_SECRET}
        ).json()

        data = advertisers['data']['list']
        for item in data:
            item['acc_id'] = item.pop('advertiser_id')
        return {'data': data}
    return None

def fetch_meta_ads_account(organization):
    ad_profile = AdIntegration.objects.filter(organization=organization, platform=Platform.META)
    if ad_profile.exists():
        access_token = ad_profile.first().access_token
        ad_accounts = requests.get(
            "https://graph.facebook.com/v18.0/me/adaccounts",
            params={"access_token": access_token},
        ).json()

        data = ad_accounts.get('data', [])
        for item in data:
            item['acc_id'] = item.pop('id')

        return ad_accounts
    return None


def fetch_meta_pages(organization):
    """
    Fetch Facebook Pages via the Business API (/{business_id}/owned_pages).
    Uses business_management permission — no pages_show_list needed.
    """
    ad_profile = AdIntegration.objects.filter(organization=organization, platform=Platform.META).first()
    if not ad_profile:
        return None

    access_token = ad_profile.access_token

    # Get all businesses the user manages
    biz_res = requests.get(
        "https://graph.facebook.com/v18.0/me/businesses",
        params={"access_token": access_token},
    ).json()

    all_pages = []
    seen_ids = set()

    for biz in biz_res.get("data", []):
        pages_res = requests.get(
            f"https://graph.facebook.com/v18.0/{biz['id']}/owned_pages",
            params={
                "access_token": access_token,
                "fields": "id,name,category,picture",
            },
        ).json()

        for page in pages_res.get("data", []):
            if page["id"] not in seen_ids:
                page["business_name"] = biz.get("name")
                page["business_id"] = biz.get("id")
                all_pages.append(page)
                seen_ids.add(page["id"])

    return {"data": all_pages}


def fetch_google_ads_account(organization):
    ad_profile = AdIntegration.objects.filter(
        organization=organization,
        platform=Platform.GOOGLE
    ).first()

    if not ad_profile:
        return None

    access_token = ad_profile.access_token

    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
        "Content-Type": "application/json",
    }

    response = requests.post(
        "https://googleads.googleapis.com/v16/customers:listAccessibleCustomers",
        headers=headers,
        json={},   # Required even if empty
        timeout=10
    )

    print(response.status_code)
    print(response.text)

    return response.json().get("resourceNames", [])


class MetaConnect(RequiredOrganizationIDMixin, APIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def get(self, request, *args, **kwargs):
        state = generate_oauth_state(request.user.id)
        
        snowflake_id = self.get_org_id()
        state = f"{state}:{snowflake_id}"
        
        params = {
            'client_id': settings.META_APP_ID,
            'redirect_uri': settings.META_REDIRECT_URI,
            "scope": "ads_read,ads_management,business_management,pages_show_list,pages_read_engagement",
            "response_type": "code",
            "auth_type": "rerequest",
            'state': state
        }
        url = "https://www.facebook.com/v18.0/dialog/oauth?" + urlencode(params)

        return Response({'redirect_url': url})

class MetaCallback(APIView):

    def get(self, request, *args, **kwargs):
        code = request.GET.get('code')
        state = request.GET.get('state')
        
        if not code or not state:
            return Response("Missing parameters", status=400)
        
        state_parts = state.split(":")
        if len(state_parts) != 2:
            return Response("Invalid state format", status=400)
            
        state_token = state_parts[0]
        org_id = state_parts[1]
        
        user_id = validate_oauth_state(state_token)
        if not user_id:
            return Response("Invalid or expired state", status=400)
        
        user = User.objects.get(id=user_id)
        
        token_res = requests.get(
            "https://graph.facebook.com/v18.0/oauth/access_token",
            params={
                "client_id": settings.META_APP_ID,
                "client_secret": settings.META_APP_SECRET,
                "redirect_uri": settings.META_REDIRECT_URI,
                "code": code,
            },
        ).json()

        if "access_token" not in token_res:
            return Response(token_res, status=400)
            
        access_token = token_res["access_token"]
        expires_in = token_res.get("expires_in", 60 * 60)
        expires_at = now() + timedelta(seconds=expires_in)

        me = requests.get(
            "https://graph.facebook.com/v18.0/me",
            params={"access_token": access_token},
        ).json()
        
        organization = Organization.objects.filter(
            memberships__user=user, snowflake_id=org_id
        ).first()
        if not organization:
            return Response({"error": "Organization not found"}, status=404)
        
        integration, created = AdIntegration.objects.update_or_create(
            organization=organization,
            platform=Platform.META,
            defaults={
                "access_token": access_token,
                "token_expires_at": expires_at,
                "account_name": me.get('name')
            }
        )

        # return Response({
        #     "success": True,
        #     "created": created,
        #     "account_name": me.get('name')
        # })
        return redirect(settings.FRONTEND_URL+"/meta-auth-callback")

class TikTokConnect(RequiredOrganizationIDMixin, APIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def get(self, request, *args, **kwargs):
        state = generate_oauth_state(request.user.id)
        
        snowflake_id = self.get_org_id()
        state = f"{state}:{snowflake_id}"
        
        params = {
            "app_id": settings.TIKTOK_APP_ID,
            "redirect_uri": settings.TIKTOK_REDIRECT_URI,
            "state": state,
            "response_type": "code",
            "scope": "advertiser.read,ads.read",
        }
        url = "https://business-api.tiktok.com/portal/auth?" + urlencode(params)

        return Response({'redirect_url': url})

class TikTokCallback(APIView):

    def get(self, request, *args, **kwargs):
        code = request.GET.get("code")
        state = request.GET.get('state')
        
        if not code or not state:
            return Response("Missing parameters", status=400)
        
        state_parts = state.split(":")
        if len(state_parts) != 2:
            return Response("Invalid state format", status=400)
            
        state_token = state_parts[0]
        org_id = state_parts[1]
        
        user_id = validate_oauth_state(state_token)
        if not user_id:
            return Response("Invalid or expired state", status=400)
        
        user = User.objects.get(id=user_id)

        res = requests.post(
            "https://business-api.tiktok.com/open_api/v1.3/oauth2/access_token/",
            json={
                "app_id": settings.TIKTOK_APP_ID,
                "secret": settings.TIKTOK_APP_SECRET,
                "auth_code": code,
            },
        ).json()

        if "data" not in res:
            return Response(res, status=400)
            
        data = res["data"]
        access_token = data["access_token"]
        expires_in = data.get("expires_in", 60 * 60)
        expires_at = now() + timedelta(seconds=expires_in)

        user_info = requests.get(
            "https://business-api.tiktok.com/open_api/v1.3/user/info/",
            headers={"Access-Token": access_token},
        ).json()

        organization = Organization.objects.filter(
            memberships__user=user, snowflake_id=org_id
        ).first()
        if not organization:
            return Response({"error": "Organization not found"}, status=404)
        
        integration, created = AdIntegration.objects.update_or_create(
            organization=organization,
            platform=Platform.TIKTOK,
            defaults={
                "access_token": access_token,
                "token_expires_at": expires_at,
                "account_name": user_info['data'].get('display_name')
            }
        )

        return Response({
            "success": True,
            "created": created,
            "account_name": user_info['data'].get('display_name')
        })


class GoogleConnect(RequiredOrganizationIDMixin, APIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def get(self, request):
        state = generate_oauth_state(request.user.id)

        snowflake_id = self.get_org_id()
        state = f"{state}:{snowflake_id}"

        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
            "scope": " ".join([
                "openid",
                "email",
                "profile",
                "https://www.googleapis.com/auth/adwords",
            ]),
        }

        auth_url = (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            + urlencode(params)
        )

        return Response({"redirect_url": auth_url})


class GoogleCallback(APIView):

    def get(self, request):
        code = request.GET.get("code")
        state = request.GET.get("state").split(":")[0]  # Extract original state without org_id
        org_id = request.GET.get("state").split(":")[1]  # Extract org_id from state
        if not code or not state:
            return Response("Missing parameters", status=400)

        user_id = validate_oauth_state(state)
        if not user_id:
            return Response("Invalid or expired state", status=400)

        user = User.objects.get(id=user_id)

        token_res = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            },
            timeout=10,
        ).json()

        if "access_token" not in token_res:
            return Response(token_res, status=400)

        access_token = token_res["access_token"]
        refresh_token = token_res.get("refresh_token")
        expires_at = now() + timedelta(seconds=token_res["expires_in"])

        # 🔹 Fetch Google user info
        user_info = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        ).json()

        google_email = user_info.get("email")

        # 🔹 Attach to organization
        organization = Organization.objects.filter(
            memberships__user=user, snowflake_id=org_id
        ).first()
        if not organization:
            return Response({"error": "Organization not found"}, status=404)

        integration, created = AdIntegration.objects.update_or_create(
            organization=organization,
            platform=Platform.GOOGLE,
            defaults={
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_expires_at": expires_at,
                "account_name": google_email,
            },
        )

        return Response({
            "success": True,
            "created": created,
            "google_email": google_email,
        })

class AdProfileListView(RequiredOrganizationIDMixin, APIView):
    permission_classes = [IsRegularPlatformUser]

    def get(self, request, *args, **kwargs):
        snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=snowflake_id).first()
        if not organization:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)
        platform = request.GET.get('platform', "META").upper()
        profiles = None
        if platform == "META":
            profiles = fetch_meta_ads_account(organization)
        elif platform == "TIKTOK":
            profiles = fetch_tiktok_ads_account(organization)
        elif platform == "GOOGLE":
            profiles = fetch_google_ads_account(organization)
        else:
            return Response({'error': 'Unsupported platform'}, status=status.HTTP_400_BAD_REQUEST)

        return Response(profiles)

class SelectAdProfileView(RequiredOrganizationIDMixin, APIView):
    permission_classes = [IsRegularPlatformUser]

    def post(self, request, *args, **kwargs):
        platform = request.data.get('platform', None)
        account_id = request.data.get('acc_id', None)

        if not platform or not account_id:
            return Response({'error': 'platfrom or account id is not provided.'}, status=status.HTTP_400_BAD_REQUEST)

        snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=snowflake_id).first()
        if not organization:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        integration = AdIntegration.objects.filter(organization=organization, platform=platform)
        if not integration.exists():
            return Response({'error': 'Integration not found'}, status=status.HTTP_400_BAD_REQUEST)

        integration=integration.first()
        integration.ad_account_id = account_id
        integration.save()

        return Response({"success": "Ad account selected."})


class MetaPageListView(RequiredOrganizationIDMixin, APIView):
    """GET — List Facebook Pages the user manages (for selecting page_id)."""
    permission_classes = [IsRegularPlatformUser]

    def get(self, request, *args, **kwargs):
        snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=snowflake_id).first()
        if not organization:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        pages = fetch_meta_pages(organization)
        if pages is None:
            return Response({'error': 'Meta integration not found.'}, status=status.HTTP_400_BAD_REQUEST)

        return Response(pages)


class SelectMetaPageView(RequiredOrganizationIDMixin, APIView):
    """POST {page_id} — Store the selected Facebook Page ID on the Meta integration."""
    permission_classes = [IsRegularPlatformUser]

    def post(self, request, *args, **kwargs):
        page_id = request.data.get('page_id')
        if not page_id:
            return Response({'error': 'page_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=snowflake_id).first()
        if not organization:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        integration = AdIntegration.objects.filter(
            organization=organization, platform=Platform.META
        ).first()
        if not integration:
            return Response({'error': 'Meta integration not found.'}, status=status.HTTP_400_BAD_REQUEST)

        integration.page_id = str(page_id)
        integration.save(update_fields=["page_id"])

        return Response({"success": "Facebook Page selected.", "page_id": integration.page_id})

class DisconnectAdIntegrationView(RequiredOrganizationIDMixin, APIView):
    permission_classes = [IsRegularPlatformUser]

    def post(self, request, *args, **kwargs):
        platform = request.data.get('platform', None)

        if not platform:
            return Response({'error': 'Platform is not provided.'}, status=status.HTTP_400_BAD_REQUEST)

        snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=snowflake_id).first()
        if not organization:
            return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)

        integration = AdIntegration.objects.filter(organization=organization, platform=platform)
        if not integration.exists():
            return Response({'error': 'Integration not found'}, status=status.HTTP_400_BAD_REQUEST)

        integration.delete()

        return Response({"success": f"{platform} integration disconnected."})
