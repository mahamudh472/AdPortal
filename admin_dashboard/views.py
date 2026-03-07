from rest_framework import generics
from rest_framework import permissions
from rest_framework.response import Response
from accounts.models import User, ContactUsMessage
from accounts.serializers import ContactUsMessageSerializer
from main.models import UnifiedCampaign, PlatformCampaign, Organization, OrganizationMember
from rest_framework.permissions import IsAdminUser
from main.serializers import CampaignSerializer, OrganizationSerializer
from rest_framework.pagination import PageNumberPagination
from .serializers import AdminNotificationSettingsSerializer, UserAdminViewSerializer, AdminReportSerializer
from django.db.models import Q, Sum, Count
from datetime import timedelta
from decimal import Decimal
import calendar
from django.utils import timezone
from .utils import get_percentage, get_last_month_objects_count, get_second_last_month_objects_count
from .models import AdminNotificationSettings, AdminReport
from finance.serializers import PaymentSerializer
from finance.models import Payment, Subscription, Plan
from rest_framework import viewsets

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

class FinanceOverviewAPIView(generics.GenericAPIView):
    permission_classes = [IsAdminUser]

    def get(self, request, *args, **kwargs):
        now = timezone.now()

        # ── Current & last month boundaries ──────────────────────────────────
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_end = current_month_start
        # Go back one month
        last_month_start = (current_month_start - timedelta(days=1)).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )

        # ── Monthly revenue (current month, paid payments) ────────────────────
        monthly_revenue = (
            Payment.objects.filter(status='paid', paid_at__gte=current_month_start)
            .aggregate(total=Sum('amount'))['total']
            or Decimal('0')
        )

        # ── MRR growth (%) vs previous month ─────────────────────────────────
        last_month_revenue = (
            Payment.objects.filter(
                status='paid',
                paid_at__gte=last_month_start,
                paid_at__lt=last_month_end,
            )
            .aggregate(total=Sum('amount'))['total']
            or Decimal('0')
        )

        if last_month_revenue == 0:
            mrr_growth = 100.0 if monthly_revenue > 0 else 0.0
        else:
            mrr_growth = round(
                float((monthly_revenue - last_month_revenue) / last_month_revenue * 100), 2
            )

        # ── Total transactions & failed payments ─────────────────────────────
        total_transactions = Payment.objects.count()
        failed_payments = Payment.objects.filter(status='failed').count()

        # ── Revenue overview – last 6 calendar months ─────────────────────────
        revenue_overview = {}
        current_year = now.year
        current_month = now.month

        for i in range(5, -1, -1):  # 5 months ago → current month
            month_num = current_month - i
            year = current_year
            while month_num <= 0:
                month_num += 12
                year -= 1

            _, last_day = calendar.monthrange(year, month_num)
            month_start = now.replace(
                year=year, month=month_num, day=1,
                hour=0, minute=0, second=0, microsecond=0,
            )
            month_end = month_start.replace(day=last_day, hour=23, minute=59, second=59, microsecond=999999)

            month_name = month_start.strftime('%b')
            month_revenue = (
                Payment.objects.filter(
                    status='paid',
                    paid_at__gte=month_start,
                    paid_at__lte=month_end,
                )
                .aggregate(total=Sum('amount'))['total']
                or Decimal('0')
            )
            revenue_overview[month_name] = float(month_revenue)

        # ── Revenue by plan ───────────────────────────────────────────────────
        revenue_by_plan = {}
        for plan in Plan.objects.filter(is_active=True):
            subscribers = Subscription.objects.filter(
                plan=plan, status__in=['active', 'trialing']
            ).count()

            plan_revenue = (
                Payment.objects.filter(status='paid', subscription__plan=plan)
                .aggregate(total=Sum('amount'))['total']
                or Decimal('0')
            )

            revenue_by_plan[plan.name] = {
                'subscribers': subscribers,
                'revenue': float(plan_revenue),
            }

        return Response({
            'monthly_revenue': float(monthly_revenue),
            'mrr_growth': mrr_growth,
            'total_transactions': total_transactions,
            'failed_payments': failed_payments,
            'revenue_overview': revenue_overview,
            'revenue_by_plan': revenue_by_plan,
        })


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
        suspended_users = all_users.filter(status='suspended').count()

        # TODO: Need to make this dynamic
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

class ChangeUserStatusAPIView(generics.UpdateAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = UserAdminViewSerializer
    queryset = User.objects.all()
    lookup_field = 'id'

    def update(self, request, *args, **kwargs):
        user = self.get_object()
        new_status = request.data.get('status', '').lower()

        if user.is_superuser:
            return Response({"error": "Cannot change status of a superuser."}, status=400)

        if new_status not in ['active', 'inactive', 'suspended']:
            return Response(
                {"error": "Invalid status. Valid options are: active, inactive, suspended."},
                status=400,
            )

        if new_status == 'active':
            user.is_active = True
            user.status = 'active'
        elif new_status == 'inactive':
            user.is_active = False
            user.status = 'inactive'
        elif new_status == 'suspended':
            user.is_active = False
            user.status = 'suspended'

        user.save()
        return Response({"message": f"User status updated to {new_status}."})


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

class TransactionListPagination(PageNumberPagination):
    max_page_size = 100
    page_size = 10

class TransactionListAPIView(generics.ListAPIView):
    permission_classes = [permissions.IsAdminUser]
    pagination_class = TransactionListPagination
    serializer_class = PaymentSerializer
    queryset = Payment.objects.all().order_by('-created_at')

    
class AdminNotificationSettingsAPIView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = AdminNotificationSettingsSerializer

    def get_object(self):
        # Each admin will have their own notification settings, so we get or create the settings for the current user
        obj, created = AdminNotificationSettings.objects.get_or_create(admin=self.request.user)
        return obj
    
    def perform_update(self, serializer):
        instance = serializer.save()
        return instance

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


class PlatformAnalysisAPIView(generics.GenericAPIView):
    """
    Returns platform-wide analytics for the admin dashboard:
      - user_growth: new & active users per month for the last 6 months
      - feature_usage: % of organisations that have used each feature
    """
    permission_classes = [IsAdminUser]

    def get(self, request, *args, **kwargs):
        from analysis.models import AnalysisDaily, Report

        now = timezone.now()
        current_year = now.year
        current_month = now.month

        # ── User Growth (last 6 months) ───────────────────────────────────────
        user_growth = []
        for i in range(5, -1, -1):  # 5 months ago → current month
            month_num = current_month - i
            year = current_year
            while month_num <= 0:
                month_num += 12
                year -= 1

            _, last_day = calendar.monthrange(year, month_num)
            month_start = now.replace(
                year=year, month=month_num, day=1,
                hour=0, minute=0, second=0, microsecond=0,
            )
            month_end = month_start.replace(
                day=last_day, hour=23, minute=59, second=59, microsecond=999999
            )

            new_users = User.objects.filter(
                joined_at__gte=month_start, joined_at__lte=month_end
            ).count()
            active_users = User.objects.filter(
                last_login__gte=month_start, last_login__lte=month_end
            ).count()

            user_growth.append({
                'month': month_start.strftime('%b'),
                'new_users': new_users,
                'active_users': active_users,
            })

        # ── Feature Usage ─────────────────────────────────────────────────────
        total_orgs = Organization.objects.count()

        def usage_pct(count):
            if total_orgs == 0:
                return 0.0
            return round((count / total_orgs) * 100, 1)

        orgs_with_campaigns = (
            UnifiedCampaign.objects.values('organization').distinct().count()
        )
        orgs_with_analytics = (
            AnalysisDaily.objects.values('organization').distinct().count()
        )
        orgs_with_reports = (
            Report.objects.values('organization').distinct().count()
        )
        # Orgs that have more than one member = team collaboration enabled
        orgs_with_teams = (
            OrganizationMember.objects
            .values('organization')
            .annotate(cnt=Count('id'))
            .filter(cnt__gt=1)
            .count()
        )
        feature_usage = [
            {'feature': 'Campaign Creation', 'usage': usage_pct(orgs_with_campaigns)},
            {'feature': 'Analytics', 'usage': usage_pct(orgs_with_analytics)},
            {'feature': 'Reports', 'usage': usage_pct(orgs_with_reports)},
            {'feature': 'Team Collaboration', 'usage': usage_pct(orgs_with_teams)},
        ]

        return Response({
            'user_growth': user_growth,
            'feature_usage': feature_usage,
        })

class ContactUsMessageViewSet(viewsets.ModelViewSet):
    queryset = ContactUsMessage.objects.all().order_by('-created_at')
    serializer_class = ContactUsMessageSerializer
    permission_classes = [permissions.IsAdminUser]

