from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework import generics, permissions, status

from main.utils.tiktok_handler import create_full_ad_for_tiktok
from .serializers import (
    CampaignSerializer, CreateAdSerializer, AICopyRequestSerializer
)
from .models import UnifiedCampaign, UnifiedStatus, Organization, OrganizationMember
from main.utils.object_handlers import (
    create_unified_campaign, create_full_ad_for_platform
)
from accounts.permissions import IsRegularPlatformUser
from rest_framework.filters import SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.pagination import PageNumberPagination
from .ai_services import generate_ad_copy
from finance.models import Payment
from .serializers import BillingHistorySerializer
from .mixins import RequiredOrganizationIDMixin

class CampaignPagination(PageNumberPagination):
	page_size = 10
	page_size_query_param = 'page_size'
	max_page_size = 100

class CampaignListAPIView(RequiredOrganizationIDMixin, generics.ListAPIView):
	serializer_class = CampaignSerializer
	permission_classes = [IsRegularPlatformUser]
	filter_backends = [SearchFilter, DjangoFilterBackend]
	pagination_class = CampaignPagination
	search_fields = ['name', 'objective']
	filterset_fields = ['status']

	def get_queryset(self):
		org_snowflake_id = self.get_org_id()
		organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
		if not organization:
			raise ValidationError({'org_id': 'Invalid organization id'})
		queryset = UnifiedCampaign.objects.filter(organization=organization).order_by('-created_at')
		return queryset

class CreateAdAPIView(generics.GenericAPIView):
	permission_classes = [IsRegularPlatformUser]
	
	def post(self, request, *args, **kwargs):
		serializer = CreateAdSerializer(data=request.data, context={'request': request})
		user = request.user

		if serializer.is_valid(raise_exception=True):
			data = serializer.validated_data
			campaign = create_unified_campaign(
				user=user,
				data=serializer.validated_data,
			)
			for platform in data['platforms']:
				create_full_ad_for_platform(campaign, data, platform)
			
			return Response(serializer.validated_data, status=status.HTTP_201_CREATED)
		else:
			return Response({'error': 'Error creating Ad'}, status=status.HTTP_400_BAD_REQUEST)


class AICopyGeneratorAPIView(generics.GenericAPIView):
	permission_classes = [IsRegularPlatformUser]
	serializer_class = AICopyRequestSerializer

	def post(self, request, *args, **kwargs):
		serializer = self.get_serializer(data=request.data)
		if not serializer.is_valid():
			return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
		data = serializer.validated_data
		generated_copy = generate_ad_copy(
			product=data['product'],
			audience=data['audience'],
			benefits=data['benefits'],
			tone=data['tone'],
			copy_type=data['copy_type']
		)
		
		return Response({'generated_copies': generated_copy}, status=status.HTTP_200_OK)

class AnalyticsAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
	permission_classes = [IsRegularPlatformUser]

	def get(self, request, *args, **kwargs):
		snowflake_id = self.get_org_id()
		organization = Organization.objects.get(snowflake_id=snowflake_id, memberships__user=request.user)
		campaigns = UnifiedCampaign.objects.filter(organization=organization)
		integration = organization.integrations.filter(platform='TIKTOK').first()
		access_token = integration.access_token
		from .utils.tiktok_handler import get_detailed_analytics as tiktok_analytics
		from django.utils import timezone
		date = timezone.now().date().strftime("%Y-%m-%d")
		data = tiktok_analytics(target_date=date)
		from .utils.analytics import save_daily_analytics
		save_daily_analytics(data, integration.ad_account_id, date)
		analytics_data = {
			'data': data
		}
		
		return Response(analytics_data, status=status.HTTP_200_OK)

class CreatePlatformCampaignAPIView(generics.GenericAPIView):
	permission_classes = [IsRegularPlatformUser]

	def post(self, request, *args, **kwargs):
		from .utils.tiktok_handler import create_platform_campaign_for_tiktok
		campaign_id = request.data.get('campaign_id')
		campaign = UnifiedCampaign.objects.get(id=campaign_id)
		create_full_ad_for_tiktok(campaign, campaign.organization.integrations.get(platform='TIKTOK'))
		# Implementation for creating platform-specific campaigns
		return Response({'message': 'Platform campaign created successfully'}, status=status.HTTP_201_CREATED)	
	
class TestTimezoneAPIView(generics.GenericAPIView):
	permission_classes = [permissions.IsAuthenticated]
	def get(self, request):
		from django.utils import timezone
		from django.http import JsonResponse
		from .utils.time_handler import utc_to_user_time

		current_time = timezone.now()
		result = utc_to_user_time(current_time, request.user.timezone)
		return Response({'current_time': result}, status=status.HTTP_200_OK)