from rest_framework import generics
from rest_framework import permissions
from rest_framework.response import Response
from apps.accounts.models import User, ContactUsMessage
from apps.accounts.serializers import ContactUsMessageSerializer
from apps.main.models import UnifiedCampaign, Organization, OrganizationMember, OrganizationStatusChoices
from rest_framework.permissions import IsAdminUser
from apps.main.serializers import SimpleCampaignSerializer, OrganizationSerializer, CampaignSerializer
from rest_framework.pagination import PageNumberPagination
from .serializers import AdminNotificationSettingsSerializer, UserAdminViewSerializer, AdminReportSerializer, UpcomingInvoiceSerializer
from django.db.models import Q, Sum, Count, F
from datetime import timedelta
from decimal import Decimal
import calendar
from django.utils import timezone
from .models import AdminNotificationSettings, AdminReport
from apps.finance.serializers import PaymentSerializer
from apps.finance.models import Payment, Subscription, Plan, Invoice
from rest_framework import viewsets
from .services.dashboard import (
    get_users_card_data, get_campaigns_card_data,
    get_chart_data, get_camaigns_count_by_platform,
    get_revenue_card_data, get_system_status
)
from .services.user_management import get_user_list, get_user_stats
from .services.organization_management import get_active_organizations, get_suspended_organizations, get_trial_organizations
from .services.finance import get_finance_overview_data
from .services.platform_analysis import get_platform_analysis_data

class DashboardAPIView(generics.GenericAPIView):
	permission_classes = [IsAdminUser]

	def get(self, request, *args, **kwargs):

		recent_campaigns = UnifiedCampaign.objects.order_by('-created_at')[:5]

		return Response(
				{
					"users": get_users_card_data(),
					"campaings": get_campaigns_card_data(),
					'revenue': get_revenue_card_data(),
					'chart_data': get_chart_data(),
					'campaings_by_platform': get_camaigns_count_by_platform(),
					'recent_campaigns': SimpleCampaignSerializer(recent_campaigns, many=True).data,
                    'system_status': get_system_status()
				}
			)

class FinanceOverviewAPIView(generics.GenericAPIView):
    permission_classes = [IsAdminUser]

    def get(self, request, *args, **kwargs):
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        data = get_finance_overview_data(start_date=start_date, end_date=end_date)
        return Response(data)


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
    page_size_query_param = "page_size"

class UserManagementAPIView(generics.GenericAPIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, *args, **kwargs):
        return Response(get_user_stats())

class UserManagementListAPIView(generics.ListAPIView):
    permission_classes = [permissions.IsAdminUser]
    pagination_class = UserListPagination
    serializer_class = UserAdminViewSerializer

    def get_queryset(self):
        return get_user_list(self.request)

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
        if user.is_staff and not request.user.is_superuser:
            return Response({"error": "Only a superuser can change the status of staff accounts."}, status=403)
        if user.pk == request.user.pk:
            return Response({"error": "You cannot change your own status."}, status=400)

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

        # Inform the affected user of the status change
        from apps.accounts.notifications import notify_user
        status_messages = {
            'active': "Your account has been reactivated.",
            'inactive': "Your account has been deactivated.",
            'suspended': "Your account has been suspended. Please contact support for assistance.",
        }
        notify_user(user, status_messages[new_status])

        return Response({"message": f"User status updated to {new_status}."})


class OrganizationListPagination(PageNumberPagination):
    max_page_size = 100
    page_size = 10

class AdminOrganizationStatsAPIView(generics.GenericAPIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request, *args, **kwargs):
        total_organizations = Organization.objects.count()

        return Response({
            'total_organizations': total_organizations,
            'active_organizations': get_active_organizations(),
            'suspended_organizations': get_suspended_organizations(),
            'trial_organizations': get_trial_organizations(),
        })

class OrganizationListAPIView(generics.ListAPIView):
    permission_classes = [permissions.IsAdminUser]
    pagination_class = OrganizationListPagination
    serializer_class = OrganizationSerializer

    def get_queryset(self):
        queryset = Organization.objects.order_by('-created_at')
        
        # Search filter
        q = self.request.query_params.get('search', '')
        if q != '':
            queryset = queryset.filter(name__icontains=q)
            
        # Status filter
        status = self.request.query_params.get('status', '')
        if status != '':
            queryset = queryset.filter(status=status.upper())
            
        return queryset

class AdminOrganizationDetailAPIView(generics.GenericAPIView):
    permission_classes = [permissions.IsAdminUser]
    queryset = Organization.objects.all()
    lookup_field = 'snowflake_id'

    def patch(self, request, *args, **kwargs):
        organization = self.get_object()
        status = request.data.get('status')
        if not status:
            return Response({'error': 'Status is required.'}, status=400)

        status_upper = status.upper()
        if status_upper not in OrganizationStatusChoices.values:
            return Response({'error': f'Invalid status. Allowed values: {OrganizationStatusChoices.values}'}, status=400)

        organization.status = status_upper
        organization.save()
        return Response({
            'message': f'Organization status updated to {status_upper} successfully.',
            'status': organization.status
        }, status=200)

    def delete(self, request, *args, **kwargs):
        organization = self.get_object()
        organization.delete()
        return Response(status=204)

class TransactionListPagination(PageNumberPagination):
    max_page_size = 100
    page_size = 10
    page_size_query_param = "page_size"

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
            generated_by=request.user if request.user and request.user.is_authenticated else None,
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

class ReportDownloadCountAPIView(generics.GenericAPIView):
    """
    Increment the download count for a specific admin report.
    This endpoint should be called when an admin downloads a report.
    """
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, *args, **kwargs):
        report_id = kwargs.get('report_id')
        try:
            report = AdminReport.objects.get(id=report_id)
        except AdminReport.DoesNotExist:
            return Response({"error": "Report not found."}, status=404)

        AdminReport.objects.filter(id=report_id).update(download_count=F('download_count') + 1)
        report.refresh_from_db()

        return Response({"message": "Download count incremented.", "download_count": report.download_count})

class PlatformAnalysisAPIView(generics.GenericAPIView):
    """
    Returns platform-wide analytics for the admin dashboard:
      - user_growth: new & active users per month for the last 6 months
      - feature_usage: % of organisations that have used each feature
    """
    permission_classes = [IsAdminUser]

    def get(self, request, *args, **kwargs):
        data = get_platform_analysis_data()
        return Response(data)

class UpcomingInvoicePagination(PageNumberPagination):
    max_page_size = 100
    page_size = 10
    page_size_query_param = "page_size"

class UpcomingInvoicesAPIView(generics.ListAPIView):
    permission_classes = [permissions.IsAdminUser]
    pagination_class = UpcomingInvoicePagination
    serializer_class = UpcomingInvoiceSerializer
    queryset = Invoice.objects.filter(status='pending').order_by('due_date')
class ContactUsMessagePagination(PageNumberPagination):
    max_page_size = 100
    page_size = 10
    page_query_param = 'page'

class ContactUsMessageViewSet(viewsets.ModelViewSet):
    queryset = ContactUsMessage.objects.all().order_by('-created_at')
    serializer_class = ContactUsMessageSerializer
    permission_classes = [permissions.IsAdminUser]
    pagination_class = ContactUsMessagePagination

    def list(self, request, *args, **kwargs):
        q = request.query_params.get('search', '')
        if q:
            self.queryset = self.queryset.filter(
                Q(email__icontains=q) | Q(message__icontains=q) | Q(name__icontains=q) | Q(subject__icontains=q)
            )
        return super().list(request, *args, **kwargs)


class AdminReportFileView(generics.GenericAPIView):
    """GET /admin/reports/<id>/file/<filename> — staff-only download of an admin report."""
    permission_classes = [permissions.IsAdminUser]

    def get(self, request, report_id, filename=None, *args, **kwargs):
        from django.http import FileResponse, Http404
        report = AdminReport.objects.filter(pk=report_id).first()
        if not report or not report.file:
            raise Http404
        try:
            handle = report.file.open('rb')
        except FileNotFoundError:
            raise Http404
        return FileResponse(handle, as_attachment=True, filename=report.name or 'report.xlsx')
