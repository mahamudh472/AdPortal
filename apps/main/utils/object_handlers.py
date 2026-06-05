from unicodedata import name
from apps.main.models import (
	AdAsset, UnifiedCampaign, AdIntegration, 
    CampaignBudget, Organization, OrganizationMember,
	PlatformCampaign, AdGroup, Ad
)
from django.db import transaction

@transaction.atomic
def create_unified_campaign(organization, data):
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

	return campaign

@transaction.atomic
def create_full_ad_for_platform(campaign, data, platform, ad_asset=None):

	integration = AdIntegration.objects.filter(
		platform=platform,
		organization=campaign.organization
	).first()
	if not integration:
		from rest_framework.exceptions import ValidationError
		raise ValidationError({platform: f'No ad integration found for {platform}. Please set up an ad account integration first.'})

	platform_campaign = PlatformCampaign.objects.create(
		unified_campaign=campaign,
		integration=integration,
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

	if data.get('ad_file') and not ad_asset:
		ad_file = data.get('ad_file')
		file_type = 'VIDEO' if ad_file.content_type.startswith('video/') else 'IMAGE'
		
		ad_asset = AdAsset.objects.create(
			organization=campaign.organization,
			file=ad_file,
			file_type=file_type
		)
	
	# Create Ad
	ad = Ad.objects.create(
		ad_group=ad_group,
		name=data.get('ad_name', f"{data['name']} - Default Ad"),
		headline=data.get('headline', ""),
		primary_text=data.get('primary_text', ""),
		description=data.get('description', ""),
		call_to_action=data.get('call_to_action', ""),
		destination_url=data.get('destination_url', ""),
	)
	if ad_asset:
		ad.assets.add(ad_asset)
	return ad
