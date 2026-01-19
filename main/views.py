from rest_framework.response import Response
from rest_framework import generics, permissions, status
from .serializers import CampaignSerializer, CreateAdSerializer
from .models import UnifiedCampaign, UnifiedStatus, Organization, OrganizationMember
from main.utils.object_handlers import create_unified_campaign
from accounts.permissions import IsRegularPlatformUser

class CampaignListAPIView(generics.ListAPIView):
	serializer_class = CampaignSerializer
	permission_classes = [IsRegularPlatformUser]

	def get_queryset(self):
		organization = Organization.objects.get(organizationmember__user=self.request.user)
		queryset = UnifiedCampaign.objects.filter(organization=organization)
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
			print(serializer.validated_data)
			return Response(serializer.data)
		else:
			return Response({'error': 'Error creating Ad'}, status=status.HTTP_400_BAD_REQUEST)