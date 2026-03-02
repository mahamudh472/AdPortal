from rest_framework import generics
from rest_framework import permissions
from rest_framework.response import Response
from accounts.models import User
from main.models import UnifiedCampaign, PlatformCampaign, Organization, OrganizationMember
from rest_framework.permissions import IsAdminUser
from main.serializers import CampaignSerializer, OrganizationSerializer
from rest_framework.pagination import PageNumberPagination
from .serializers import AdminNotificationSettingsSerializer, UserAdminViewSerializer, AdminReportSerializer
from django.db.models import Q
from datetime import timedelta
from django.utils import timezone
from .utils import get_percentage, get_last_month_objects_count, get_second_last_month_objects_count
from .models import AdminNotificationSettings, AdminReport

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

		recent_campaigns = UnifiedCampaign.objects.order_by('-created_at')[:5]

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
				Q(email__icontains=q) | Q(full_name__icontains=q)
				)
		return User.objects.all()

class OrganizationListPagination(PageNumberPagination):
    max_page_size = 100
    page_size = 10

class OrganizationListAPIView(generics.ListAPIView):
    permission_classes = [permissions.IsAdminUser]
    pagination_class = OrganizationListPagination
    serializer_class = OrganizationSerializer

    def get_queryset(self):
        q = self.request.query_params.get('search', '')
        if q != '':
            return Organization.objects.filter(name__icontains=q)
        return Organization.objects.all()

    
class AdminNotificationSettingsAPIView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = AdminNotificationSettingsSerializer

    def get_object(self):
        # Each admin will have their own notification settings, so we get or create the settings for the current user
        obj, created = AdminNotificationSettings.objects.get_or_create(admin=self.request.user)
        return obj
    
    def perform_update(self, serializer):
        instance = serializer.save()
        # Here you can add any additional logic that needs to happen after updating the settings
        # For example, you might want to send a confirmation email or log the change
        # For now, we'll just pass
        pass


# ── Admin Analytics Reports ───────────────────────────────────────────────────

VALID_ADMIN_METRICS = {
    'revenue_overview',
    'revenue_by_plan',
    'user_growth',
    'feature_usage',
    'monthly_revenue',
    'mrr_growth',
    'total_transactions',
    'failed_payments',
}

VALID_REPORT_TYPES = {'weekly', 'monthly', 'quarterly', 'custom'}


class AdminReportPagination(PageNumberPagination):
    page_size = 15
    page_size_query_param = 'page_size'
    max_page_size = 100


class AdminReportListView(generics.ListAPIView):
    """List all generated admin reports, newest first."""
    permission_classes = [permissions.IsAdminUser]
    serializer_class = AdminReportSerializer
    pagination_class = AdminReportPagination
    queryset = AdminReport.objects.order_by('-created_at')


class GenerateAdminReportView(generics.GenericAPIView):
    """
    Generate a platform-wide admin analytics report.

    POST body:
    {
        "report_type": "weekly" | "monthly" | "quarterly" | "custom",
        "included_metrics": ["revenue_overview", "user_growth", ...],  // optional, defaults to all
        "start_date": "YYYY-MM-DD",  // required only when report_type == "custom"
        "end_date":   "YYYY-MM-DD"   // required only when report_type == "custom"
    }
    """
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, *args, **kwargs):
        from datetime import datetime, timedelta

        report_type = request.data.get('report_type', 'weekly').lower()
        included_metrics = request.data.get('included_metrics', [])

        if report_type not in VALID_REPORT_TYPES:
            return Response(
                {
                    "error": (
                        f"Invalid report_type: '{report_type}'. "
                        f"Valid options are: {', '.join(sorted(VALID_REPORT_TYPES))}"
                    )
                },
                status=400,
            )

        if included_metrics:
            invalid = set(m.lower() for m in included_metrics) - VALID_ADMIN_METRICS
            if invalid:
                return Response(
                    {
                        "error": (
                            f"Invalid metrics: {', '.join(sorted(invalid))}. "
                            f"Valid options are: {', '.join(sorted(VALID_ADMIN_METRICS))}"
                        )
                    },
                    status=400,
                )
            included_metrics = [m.lower() for m in included_metrics]

        today = datetime.now().date()

        if report_type == 'custom':
            start_str = request.data.get('start_date')
            end_str = request.data.get('end_date')

            if not start_str or not end_str:
                return Response(
                    {"error": "Custom reports require both 'start_date' and 'end_date' (YYYY-MM-DD)."},
                    status=400,
                )

            try:
                start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
            except ValueError:
                return Response({"error": "Invalid date format. Use YYYY-MM-DD."}, status=400)

            if start_date > end_date:
                return Response({"error": "start_date must be before or equal to end_date."}, status=400)

        elif report_type == 'weekly':
            end_date = today
            start_date = today - timedelta(days=7)

        elif report_type == 'monthly':
            end_date = today
            start_date = today - timedelta(days=30)

        elif report_type == 'quarterly':
            end_date = today
            start_date = today - timedelta(days=90)

        report = AdminReport.objects.create(
            name="Generating...",
            report_type=report_type,
            status=AdminReport.Status.PENDING,
            included_metrics=included_metrics,
            start_date=start_date,
            end_date=end_date,
        )

        from .tasks import generate_admin_report_task
        generate_admin_report_task.delay(report.id)

        return Response(
            {
                "message": "Admin report is being generated. Check back shortly.",
                "report_id": report.id,
            },
            status=202,
        )

