from collections import UserString
from rest_framework import generics
from rest_framework.response import Response
from accounts.models import User
from main.models import Campaign
from rest_framework.permissions import IsAdminUser

class DashboardAPIView(generics.GenericAPIView):
	permission_classes = [IsAdminUser]

	def get(request, *args, **kwargs):

		# TODO: Need to implement month filtered data.
		users = User.objects.count()
		campaings = Campaign.objects.all()

		# TODO: Need to make revenue dynamic

		revenue = 0

		meta_campaigns = campaings.filter(integration__platform='META').count()
		google_campaigns = campaings.filter(integration__platform='GOOGLE').count()
		tiktok_campaigns = campaings.filter(integration__platform='TIKTOK').count()

		recent_campaigns = campaings.order_by('-created_at')[:5]

		return Response(
				{
					"users": users,
					"campaings": campaings.count(),
					'revenue': revenue,
					'campaings_by_platform':{
					'meta': meta_campaigns,
					'google': google_campaigns,
					'tiktok': tiktok_campaigns
					},
					'recent_campaigns': recent_campaigns

				}
			)
