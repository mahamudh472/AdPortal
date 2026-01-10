from rest_framework import generics
from rest_framework import permissions
from rest_framework.response import Response
from accounts.models import User
from main.models import Platform, UnifiedCampaign, PlatformCampaign
from rest_framework.permissions import IsAdminUser
from main.serializers import CampaignSerializer
from rest_framework.pagination import PageNumberPagination
from .serializers import UserAdminViewSerializer
from django.db.models import Q
from datetime import timedelta
from django.utils import timezone
from .utils import get_percentage, get_last_month_objects_count, get_second_last_month_objects_count

class DashboardAPIView(generics.GenericAPIView):
	permission_classes = [IsAdminUser]

	def get(request, *args, **kwargs):

		users = User.objects.all()
		last_month_users = get_last_month_objects_count(users)
		second_last_month_users = get_second_last_month_objects_count(users)
		user_info_percentage = get_percentage(last_month_users, second_last_month_users)

		campaings = PlatformCampaign.objects.all()
		last_month_campaigns = get_last_month_objects_count(campaings)
		second_last_month_campaigns = get_second_last_month_objects_count(campaings)
		campaign_info_percentage = get_percentage(last_month_campaigns, second_last_month_campaigns)

		# TODO: Need to make revenue dynamic

		revenue = 0

		chart_data = [
		    { 'month': "Jan", 'users': 2000, 'revenue': 2400 },
		    { 'month': "Feb", 'users': 4000, 'revenue': 4200 },
		    { 'month': "Mar", 'users': 7000, 'revenue': 6800 },
		    { 'month': "Apr", 'users': 9000, 'revenue': 7600 },
		    { 'month': "May", 'users': 10500, 'revenue': 8900 },
		    { 'month': "Jun", 'users': 12000, 'revenue': 11000 },
		    { 'month': "Jul", 'users': 13500, 'revenue': 12500 },
		  ];

		meta_campaigns = campaings.filter(integration__platform='META').count()
		google_campaigns = campaings.filter(integration__platform='GOOGLE').count()
		tiktok_campaigns = campaings.filter(integration__platform='TIKTOK').count()

		recent_campaigns = campaings.order_by('-created_at')[:5]

		return Response(
				{
					"users": {
						"value": users.count(),
						"past_month": last_month_users,
						'percentage': user_info_percentage
					},
					"campaings": {
						'value': campaings.count(),
						'last_month': last_month_campaigns,
						'percentage': campaign_info_percentage
					},
					'revenue': {
						'value': revenue,
						'percentage': 0
					},
					'chart_data': chart_data,
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
	queryset = UnifiedCampaign.objects.all()
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

