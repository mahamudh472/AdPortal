from main.models import UnifiedCampaign, AdIntegration, CampaignBudget

def create_unified_campaign(user, name, objective, budgets):

	campaign = UnifiedCampaign.objects.create(
		user=user,
		name=name,
		objective=objective,
	)
	for budget in budgets:
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
