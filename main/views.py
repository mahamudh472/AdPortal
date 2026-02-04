from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework import generics, status
from django.db import models
from main.utils.tiktok_handler import create_full_ad_for_tiktok
from .serializers import (
    CampaignSerializer, CreateAdSerializer, AICopyRequestSerializer, OrganizationSerializer, TeamMemberSerializer
)
from .models import UnifiedCampaign, Organization, OrganizationMember
from main.utils.object_handlers import (
    create_unified_campaign, create_full_ad_for_platform
)
from accounts.permissions import IsAdminOrOwnerOfOrganization, IsRegularPlatformUser, IsOrganizationMember
from rest_framework.filters import SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.pagination import PageNumberPagination
from .ai_services import generate_ad_copy
from .mixins import RequiredOrganizationIDMixin
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes



@extend_schema(
		parameters=[
			OpenApiParameter(
				name="org_id",
				type=OpenApiTypes.STR,
				location=OpenApiParameter.QUERY,
				required=True,
				description="Organization Snowflake ID"
			)
		]
	)
class OrganizationRetrieveUpdateAPIView(RequiredOrganizationIDMixin, generics.RetrieveUpdateAPIView):
	serializer_class = OrganizationSerializer
	permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

	def get_object(self):
		user = self.request.user
		snoflake_id = self.get_org_id()
		organization = Organization.objects.filter(snowflake_id=snoflake_id, memberships__user=user).first()
		if not organization:
			raise ValidationError({'org_id': 'Invalid organization id'})
		return organization


class CampaignPagination(PageNumberPagination):
	page_size = 10
	page_size_query_param = 'page_size'
	max_page_size = 100

@extend_schema(
	parameters=[
		OpenApiParameter(
			name="org_id",
			type=OpenApiTypes.STR,
			location=OpenApiParameter.QUERY,
			required=True,
			description="Organization Snowflake ID"
		)
	]
)
class CampaignListAPIView(RequiredOrganizationIDMixin, generics.ListAPIView):
	serializer_class = CampaignSerializer
	permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
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

@extend_schema(
	parameters=[
		OpenApiParameter(
			name="org_id",
			type=OpenApiTypes.STR,
			location=OpenApiParameter.QUERY,
			required=True,
			description="Organization Snowflake ID"
		)
	]
)
class CreateAdAPIView(generics.GenericAPIView):
	permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
	
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


@extend_schema(
	parameters=[
		OpenApiParameter(
			name="org_id",
			type=OpenApiTypes.STR,
			location=OpenApiParameter.QUERY,
			required=True,
			description="Organization Snowflake ID"
		)
	]
)
class AICopyGeneratorAPIView(generics.GenericAPIView):
	permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
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

@extend_schema(
	parameters=[
		OpenApiParameter(
			name="org_id",
			type=OpenApiTypes.STR,
			location=OpenApiParameter.QUERY,
			required=True,
			description="Organization Snowflake ID"
		)
	]
)
class AnalyticsAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
	permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

	def get(self, request, *args, **kwargs):
		snowflake_id = self.get_org_id()
		organization = Organization.objects.get(snowflake_id=snowflake_id, memberships__user=request.user)
		campaigns = UnifiedCampaign.objects.filter(organization=organization)
		integration = organization.integrations.filter(platform='TIKTOK').first()
		if not integration:
			return Response({'error': 'No TikTok integration found for this organization.'}, status=status.HTTP_400_BAD_REQUEST)
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

@extend_schema(
	parameters=[
		OpenApiParameter(
			name="org_id",
			type=OpenApiTypes.STR,
			location=OpenApiParameter.QUERY,
			required=True,
			description="Organization Snowflake ID"
		)
	]
)
class CreatePlatformCampaignAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
	permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

	def post(self, request, *args, **kwargs):
		from .utils.tiktok_handler import create_platform_campaign_for_tiktok
		campaign_id = request.data.get('campaign_id')
		campaign = UnifiedCampaign.objects.get(id=campaign_id)
		create_full_ad_for_tiktok(campaign, campaign.organization.integrations.get(platform='TIKTOK'))
		# Implementation for creating platform-specific campaigns
		return Response({'message': 'Platform campaign created successfully'}, status=status.HTTP_201_CREATED)	

@extend_schema(
	parameters=[
		OpenApiParameter(
			name="org_id",
			type=OpenApiTypes.STR,
			location=OpenApiParameter.QUERY,
			required=True,
			description="Organization Snowflake ID"
		)
	]
)

@extend_schema(
	parameters=[
		OpenApiParameter(
			name="org_id",
			type=OpenApiTypes.STR,
			location=OpenApiParameter.QUERY,
			required=True,
			description="Organization Snowflake ID"
		)
	]
)
class TeamAPIView(generics.GenericAPIView):
	permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
	serializer_class = TeamMemberSerializer

	def get(self, request, *args, **kwargs):
		org_snowflake_id = request.query_params.get('org_id')
		organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
		if not organization:
			raise ValidationError({'org_id': 'Invalid organization id'})
		
		data = OrganizationMember.objects.filter(organization=organization).aggregate(
			total_members=models.Count('id'),
			active_members=models.Count('id', filter=models.Q(user__is_active=True)),
			inactive_members=models.Count('id', filter=models.Q(user__is_active=False)),
			pending_invitations=models.Count('id', filter=models.Q(status='PENDING'))
		)

		return Response(data, status=status.HTTP_200_OK)

@extend_schema(
	parameters=[
		OpenApiParameter(
			name="org_id",
			type=OpenApiTypes.STR,
			location=OpenApiParameter.QUERY,
			required=True,
			description="Organization Snowflake ID"
		)
	]
)
class TeamMemberListAPIView(RequiredOrganizationIDMixin, generics.ListAPIView):
	serializer_class = TeamMemberSerializer
	permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

	def get_queryset(self):
		org_snowflake_id = self.get_org_id()
		organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
		if not organization:
			raise ValidationError({'org_id': 'Invalid organization id'})
		queryset = OrganizationMember.objects.filter(organization=organization).select_related('user')
		return queryset

@extend_schema(
	parameters=[
		OpenApiParameter(
			name="org_id",
			type=OpenApiTypes.STR,
			location=OpenApiParameter.QUERY,
			required=True,
			description="Organization Snowflake ID"
		)
	]
)
class UpdateDeleteTeamMemberAPIView(generics.RetrieveUpdateDestroyAPIView):
	serializer_class = TeamMemberSerializer
	permission_classes = [IsRegularPlatformUser, IsAdminOrOwnerOfOrganization]
	lookup_field = 'id'

	def get_queryset(self):
		org_snowflake_id = self.request.query_params.get('org_id')
		organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
		if not organization:
			raise ValidationError({'org_id': 'Invalid organization id'})
		# TODO: Ensure authority to update/delete team members
		queryset = OrganizationMember.objects.filter(organization=organization).select_related('user')
		return queryset
	
	# override update and delete for ownership sothat admin can't make owner or delete owner
	def update(self, request, *args, **kwargs):
		instance = self.get_object()
		if instance.role == 'OWNER':
			return Response({'error': 'Cannot modify the owner of the organization.'}, status=status.HTTP_403_FORBIDDEN)
		return super().update(request, *args, **kwargs)

	def destroy(self, request, *args, **kwargs):
		instance = self.get_object()
		if instance.role == 'OWNER':
			return Response({'error': 'Cannot delete the owner of the organization.'}, status=status.HTTP_403_FORBIDDEN)
		return super().destroy(request, *args, **kwargs)