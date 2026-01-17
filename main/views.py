from rest_framework.response import Response
from rest_framework import generics, permissions, status
from .serializers import CampaignSerializer, CreateAdSerializer
from .models import UnifiedCampaign, UnifiedStatus
from main.utils.object_handlers import create_unified_campaign

class CampaignListAPIView(generics.ListAPIView):
	serializer_class = CampaignSerializer
	permission_classes = [permissions.IsAuthenticated]

	def get_queryset(self):
		queryset = UnifiedCampaign.objects.filter(user=self.request.user)
		return queryset

class CreateAdAPIView(generics.GenericAPIView):
	permission_classes = [permissions.IsAuthenticated]
	
	def post(self, request, *args, **kwargs):
		serializer = CreateAdSerializer(data=request.data)
		user = request.user
		if serializer.is_valid(raise_exception=True):
			data = serializer.validated_data
			campaign = create_unified_campaign(
				user=user,
				name=data.get('campaign_name'),
				objective=data.get('objective'),
				budgets=data.get('budgets')
			)
			print(serializer.validated_data)
			return Response(serializer.data)
		else:
			return Response({'error': 'Error creating Ad'}, status=status.HTTP_400_BAD_REQUEST)