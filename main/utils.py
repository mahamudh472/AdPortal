from .models import UnifiedCampaign, PlatformCampaign
from rest_framework.response import Response

def create_Campaign_locally(user, validated_data):

	# Create Campaign
	try:
		campaign = UnifiedCampaign.objects.create(
			user=user,
			name=validated_data['campaign_name'],
			objective=validated_data['objective'],
			budget_type=validated_data['budget_type'],
			daily_budget_minor=int(validated_data['budget'])*100,
		)

		# Change status
		if validated_data['status']:
			campaign.status = "DRAFT"
		campaign.save()

	except Exception as e:
		return Response({'error': f'Error creating Campaign: {e}'})

	# Create Platform Campaign locally

	# PlatformCampaign.objects.create(
	# 	unified_campaign
	# )