from rest_framework.generics import GenericAPIView, ListAPIView
from main.mixins import RequiredOrganizationIDMixin
from rest_framework.response import Response
from main.models import Organization
from .models import AnalysisDaily, Report
from .serializers import ReportSerializer
from .tasks import generate_report_task
from accounts.permissions import IsOrganizationMember, IsAdminOrOwnerOfOrganization, IsRegularPlatformUser
from rest_framework.pagination import PageNumberPagination

VALID_PLATFORMS = {'META', 'TIKTOK', 'GOOGLE'}
VALID_METRICS = {'spend', 'impressions', 'clicks', 'ctr', 'cpc', 'roas'}

class ReportPagination(PageNumberPagination):
    page_size = 15
    page_size_query_param = 'page_size'
    max_page_size = 100

class ReportListView(RequiredOrganizationIDMixin, ListAPIView):
    serializer_class = ReportSerializer
    permission_classes = [IsOrganizationMember | IsAdminOrOwnerOfOrganization | IsRegularPlatformUser]
    pagination_class = ReportPagination
    
    def get_queryset(self):
        org_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=org_id).first()
        if organization:
            return Report.objects.filter(organization=organization).order_by('-created_at')
        return Report.objects.none()


class GenerateReportView(RequiredOrganizationIDMixin, GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsAdminOrOwnerOfOrganization]

    def post(self, request, *args, **kwargs):
        from datetime import datetime, timedelta
        
        org_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=org_id).first()

        if not organization:
            return Response({"error": "Organization not found"}, status=404)

        # ── Parse request body ──
        report_type = request.data.get('report_type', 'custom')
        included_platforms = request.data.get('included_platforms', [])
        included_metrics = request.data.get('included_metrics', [])

        # Validate platforms
        if included_platforms:
            invalid = set(p.upper() for p in included_platforms) - VALID_PLATFORMS
            if invalid:
                return Response(
                    {"error": f"Invalid platforms: {', '.join(invalid)}. Valid options are: {', '.join(VALID_PLATFORMS)}"},
                    status=400,
                )
            included_platforms = [p.upper() for p in included_platforms]
        
        # Validate metrics
        if included_metrics:
            invalid = set(m.lower() for m in included_metrics) - VALID_METRICS
            if invalid:
                return Response(
                    {"error": f"Invalid metrics: {', '.join(invalid)}. Valid options are: {', '.join(VALID_METRICS)}"},
                    status=400,
                )
            included_metrics = [m.lower() for m in included_metrics]

        # ── Handle date ranges based on report_type ──
        start_date = None
        end_date = None
        
        if report_type == 'custom':
            # For custom reports, require start_date and end_date
            start_date_str = request.data.get('start_date')
            end_date_str = request.data.get('end_date')
            
            if not start_date_str or not end_date_str:
                return Response(
                    {"error": "Custom reports require both 'start_date' and 'end_date' in YYYY-MM-DD format"},
                    status=400,
                )
            
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {"error": "Invalid date format. Use YYYY-MM-DD format"},
                    status=400,
                )
            
            if start_date > end_date:
                return Response(
                    {"error": "start_date must be before or equal to end_date"},
                    status=400,
                )
        
        elif report_type == 'weekly':
            # Last 7 days
            end_date = datetime.now().date()
            start_date = end_date - timedelta(days=7)
        
        elif report_type == 'monthly':
            # Last 30 days
            end_date = datetime.now().date()
            start_date = end_date - timedelta(days=30)
        
        else:
            return Response(
                {"error": f"Invalid report_type: '{report_type}'. Valid options are: 'weekly', 'monthly', 'custom'"},
                status=400,
            )

        # Create a pending Report record
        report = Report.objects.create(
            organization=organization,
            name="Generating...",
            report_type=report_type,
            status=Report.Status.PENDING,
            included_platforms=included_platforms,
            included_metrics=included_metrics,
            start_date=start_date,
            end_date=end_date,
        )

        # Dispatch the background task
        generate_report_task.delay(report.id)

        return Response({
            "message": "Generating report, you will get a notification when completed.",
            "report_id": report.id,
        }, status=202)
