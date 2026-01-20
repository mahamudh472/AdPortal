from rest_framework.response import Response
from rest_framework import generics, permissions, status
from .serializers import CampaignSerializer, CreateAdSerializer
from .models import UnifiedCampaign, UnifiedStatus, Organization, OrganizationMember
from main.utils.object_handlers import (
    create_unified_campaign, create_full_ad_for_platform
)
from accounts.permissions import IsRegularPlatformUser
from rest_framework.filters import SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.pagination import PageNumberPagination

class CampaignPagination(PageNumberPagination):
	page_size = 10
	page_size_query_param = 'page_size'
	max_page_size = 100

class CampaignListAPIView(generics.ListAPIView):
	serializer_class = CampaignSerializer
	permission_classes = [IsRegularPlatformUser]
	filter_backends = [SearchFilter, DjangoFilterBackend]
	pagination_class = CampaignPagination
	search_fields = ['name', 'objective']
	filterset_fields = ['status']

	def get_queryset(self):
		organization = Organization.objects.get(organizationmember__user=self.request.user)
		queryset = UnifiedCampaign.objects.filter(organization=organization).order_by('-created_at')
		return queryset

class CreateAdAPIView(generics.GenericAPIView):
	permission_classes = [IsRegularPlatformUser]
	
	def post(self, request, *args, **kwargs):
		serializer = CreateAdSerializer(data=request.data, context={'request': request})
		user = request.user
		print(request.data)
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
		