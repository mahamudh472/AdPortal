from unicodedata import name
from main.models import (
	AdAsset, UnifiedCampaign, AdIntegration, 
    CampaignBudget, Organization, OrganizationMember,
	PlatformCampaign, AdGroup, Ad
)
from django.db import transaction

@transaction.atomic
def create_unified_campaign(user, data):
	organization = Organization.objects.get(organizationmember__user=user)
	campaign = UnifiedCampaign.objects.create(
		organization=organization,
		name=data['name'],
		objective=data['objective']
	)
	for budget in data['budgets']:
		CampaignBudget.objects.update_or_create(
			campaign=campaign,
			platform=budget['platform'],

			defaults={
				'budget_type':budget['budget_type'],
				'daily_budget_minor':budget['budget'],
				'start_date':budget['start_date'],
			    'end_date':budget['end_date'],
				'run_continuously':budget['run_continuously'],
			}
		)

	# Create PlatformCampaign

	platform_campaign = PlatformCampaign.objects.create(
		unified_campaign=campaign,
		integration=AdIntegration.objects.get(platform=budget['platform']),
		platform_campaign_id=None,
	)

	# Create AdGroup
	ad_group = AdGroup.objects.create(
		platform_campaign=platform_campaign,
		name=f"{data['name']} - Default Ad Group",
		targeting_config={
			"min_age": data.get('min_age'),
			"max_age": data.get('max_age'),
			"gender": data.get('gender'),
			"locations": data.get('locations'),
			"keywords": data.get('keywords'),
		},
	)

	if data.get('ad_file'):
		ad_file = data.get('ad_file')
		file_type = ad_file.content_type
		
		AdAsset.objects.create(
			organization=campaign.organization,
			file=ad_file,
			file_type=file_type
		)
	
	# Create Ad
	ad = Ad.objects.create(
		ad_group=ad_group,
		name=f"{data['name']} - Default Ad",
		headline=data.get('headline', ""),
		primary_text=data.get('primary_text', ""),
		description=data.get('description', ""),
		call_to_action=data.get('call_to_action', ""),
		destination_url=data.get('destination_url', ""),
		platform_asset_id=None
	)

	return campaign
