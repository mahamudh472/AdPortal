from collections import UserString
from operator import ge
from rest_framework import generics
from rest_framework import permissions
from rest_framework.response import Response
from accounts.models import User
from main.models import Campaign
from rest_framework.permissions import IsAdminUser
from main.serializers import CampaignSerializer
from rest_framework.pagination import PageNumberPagination
from .serializers import UserAdminViewSerializer
from django.db.models import Q
from datetime import timedelta
from django.utils import timezone

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
					'recent_campaigns': CampaignSerializer(recent_campaigns, many=True).data

				}
			)

class CampaignListPagination(PageNumberPagination):
	max_page_size = 100
	page_size = 10


class CampaignListAPIView(generics.ListAPIView):
	serializer_class = CampaignSerializer
	permission_classes = [permissions.IsAdminUser]
	queryset = Campaign.objects.all()
	pagination_class = CampaignListPagination

class UserListPagination(PageNumberPagination):
	max_page_size = 100
	page_size = 10

class UserManagementAPIView(generics.GenericAPIView):
	permission_classes = [permissions.IsAdminUser]

	def get(self, *args, **kwargs):
		all_users = User.objects.all()
		total_users = all_users.count()
		past_date = timezone.now() - timedelta(days=7)
		last_week_created = all_users.filter(joined_at__gte=past_date).count()
		active_users = all_users.filter(is_active=True).count()
		
		# TODO: Need to make this dynamic
		suspended_users = 0
		trial_users = 0

		return Response({
			'total_users': {
				'value': total_users,
				'last_week': last_week_created
			},
			'active_users': active_users,
			'suspended_users': suspended_users,
			'trial_users': trial_users
			})


class UserManagementListAPIView(generics.ListAPIView):
	permission_classes = [permissions.IsAdminUser]
	pagination_class = UserListPagination
	serializer_class = UserAdminViewSerializer


	def get_queryset(self):
		q = self.request.query_params.get('search', '')
		if q!='':
			return User.objects.filter(
				Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
				)
		return User.objects.all()

