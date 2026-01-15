from datetime import timedelta
from os import access, stat
from requests.exceptions import RetryError
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from urllib.parse import urlencode
from django.conf import settings
import requests
from django.utils.timezone import now
from accounts.models import User
from main.models import AdIntegration, Platform
from rest_framework import status

def fetch_tiktok_ads_account(user):
	ad_profile = AdIntegration.objects.filter(user=user, platform=Platform.TIKTOK)
	if ad_profile.exists():
		access_token = ad_profile.first().access_token
		advertisers = requests.get(
		    "https://business-api.tiktok.com/open_api/v1.3/oauth2/advertiser/get/",
		    headers={"Access-Token": access_token},
		    params={"app_id": settings.TIKTOK_APP_ID, 'secret': settings.TIKTOK_APP_SECRET}
		).json()

		data = advertisers['data']['list']
		for item in data:
			item['id'] = item.pop('advertiser_id')
		return {'data': data}
	return None

def fetch_meta_ads_account(user):
	ad_profile = AdIntegration.objects.filter(user=user, platform=Platform.META)
	if ad_profile.exists():
		access_token = ad_profile.first().access_token
		ad_accounts = requests.get(
		    "https://graph.facebook.com/v18.0/me/adaccounts",
		    params={"access_token": access_token},
		).json()

		return ad_accounts
	return None

class MetaConnect(APIView):
	permission_classes = [IsAuthenticated]

	def get(self, request, *args, **kwargs):
		user = request.user
		params = {
			'client_id': settings.META_APP_ID,
			'redirect_uri': "https://sisterlike-tastelessly-mike.ngrok-free.dev/api/auth/meta/callback/",
			"scope": "ads_read,ads_management,business_management",
	        "response_type": "code",
	        'state': str(user.id)
		}
		url = "https://www.facebook.com/v18.0/dialog/oauth?" + urlencode(params)

		return Response({'redirect_url': url})

class MetaCallback(APIView):

	def get(self, request, *args, **kwargs):
		code = request.GET.get('code')
		user_id = request.GET.get('state')
		user = User.objects.get(id=str(user_id))
		token_res = requests.get(
	        "https://graph.facebook.com/v18.0/oauth/access_token",
	        params={
	            "client_id": settings.META_APP_ID,
	            "client_secret": settings.META_APP_SECRET,
	            "redirect_uri": 'https://sisterlike-tastelessly-mike.ngrok-free.dev/api/auth/meta/callback/',
	            "code": code,
	        },
	    ).json()

		print(token_res)
		access_token = token_res["access_token"]
		expires_in = token_res.get("expires_in", 60 * 60)

		exprires_at = now() + timedelta(seconds=expires_in)

		me = requests.get(
		    "https://graph.facebook.com/v18.0/me",
		    params={"access_token": access_token},
		).json()
		print("User Info:", me)

		ad_profile = AdIntegration.objects.update_or_create(
			user=user,
			platform=Platform.META,
			defaults={
				"access_token":access_token,
				"token_expires_at":exprires_at,
				"account_name":me.get('name')	
			}
			
		)
		print(ad_profile)


		return Response({"Successful"})

class TikTokConnect(APIView):
	permission_classes = [IsAuthenticated]

	def get(self, request, *args, **kwargs):
		params = {
	        "app_id": settings.TIKTOK_APP_ID,
	        "redirect_uri": "https://sisterlike-tastelessly-mike.ngrok-free.dev/api/auth/tiktok/callback/",
	        "state": request.user.id,
	        "response_type": "code",
	        "scope": "advertiser.read,ads.read",
	    }
		print(settings.TIKTOK_APP_ID)
		url = "https://business-api.tiktok.com/portal/auth?" + urlencode(params)

		return Response({'redirect_url': url})

class TikTokCallback(APIView):

	def get(self, request, *args, **kwargs):
		code = request.GET.get("code")
		user_id = request.GET.get('state')
		user = User.objects.get(id=str(user_id))

		res = requests.post(
	        "https://business-api.tiktok.com/open_api/v1.3/oauth2/access_token/",
	        json={
	            "app_id": settings.TIKTOK_APP_ID,
	            "secret": settings.TIKTOK_APP_SECRET,
	            "auth_code": code,
	        },
	    ).json()

		data = res["data"]
		print(res)

		access_token = data["access_token"]
		# refresh_token = data["refresh_token"]
		expires_in = data.get("expires_in", 60 * 60)

		exprires_at = now() + timedelta(seconds=expires_in)

		user_info = requests.get(
		    "https://business-api.tiktok.com/open_api/v1.3/user/info/",
		    headers={"Access-Token": access_token},
		).json()

		print(user_info)

		ad_profile, created = AdIntegration.objects.update_or_create(
			user=user,
			platform=Platform.TIKTOK,
			defaults={
				"access_token":access_token,
				"token_expires_at":exprires_at,
				"account_name":user_info['data'].get('display_name')	
			}
			
		)

		print(ad_profile, created)

		return Response("Successful")



class AdProfileListView(APIView):
	permission_classes = [IsAuthenticated]

	def get(self, request, *args, **kwargs):
		user = request.user
		platform = request.GET.get('platform', "META").upper()
		profiles = None
		if platform == "META":
			profiles = fetch_meta_ads_account(user)
		elif platform == "TIKTOK":
			profiles = fetch_tiktok_ads_account(user)

		return Response(profiles)

class SelectAdProfileView(APIView):
	permission_classes = [IsAuthenticated]

	def post(self, request, *args, **kwargs):
		platform = request.data.get('platform', None)
		account_id = request.data.get('acc_id', None)

		if not platform or not account_id:
			return Response({'error': 'platfrom or account id is not provided.'}, status=status.HTTP_400_BAD_REQUEST)

		user = request.user 
		integration = AdIntegration.objects.filter(user=user, platform=platform)
		if not integration.exists():
			return Response({'error': 'Integration not found'}, status=status.HTTP_400_BAD_REQUEST)

		integration=integration.first()
		integration.ad_account_id = account_id
		integration.save()

		return Response({"success": "Ad account selected."})


