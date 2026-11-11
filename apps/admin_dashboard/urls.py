from django.urls import path
from . import views
from rest_framework.routers import DefaultRouter

from rest_framework.routers import APIRootView
from rest_framework.permissions import IsAdminUser


class StaffOnlyAPIRootView(APIRootView):
    permission_classes = [IsAdminUser]


class StaffOnlyRouter(DefaultRouter):
    APIRootView = StaffOnlyAPIRootView


router = StaffOnlyRouter()
# Register contact us message viewset
router.register(r'contact-messages', views.ContactUsMessageViewSet, basename='contact-message')

urlpatterns = [
	path('dashboard/', views.DashboardAPIView.as_view()),
	path('campaigns/', views.CampaignListAPIView.as_view()),
	path('user-management/', views.UserManagementAPIView.as_view()),
	path('user-management-list/', views.UserManagementListAPIView.as_view()),
    path('user-management/<uuid:id>/', views.ChangeUserStatusAPIView.as_view()),
    path('organizations/', views.OrganizationListAPIView.as_view()),
    path('organizations/stats/', views.AdminOrganizationStatsAPIView.as_view()),
    path('organizations/<str:snowflake_id>/', views.AdminOrganizationDetailAPIView.as_view()),
    path('transactions/', views.TransactionListAPIView.as_view()),
    path('notification-settings/', views.AdminNotificationSettingsAPIView.as_view()),
    path('reports/', views.AdminReportListView.as_view(), name='admin-report-list'),
    path('reports/<int:report_id>/file/<str:filename>', views.AdminReportFileView.as_view(), name='admin-report-file'),
    path('reports/<int:report_id>/download/', views.ReportDownloadCountAPIView.as_view(), name='admin-report-detail'),
    path('generate-report/', views.GenerateAdminReportView.as_view(), name='admin-generate-report'),
    path('finance/', views.FinanceOverviewAPIView.as_view(), name='admin-finance-overview'),
    path('platform-analysis/', views.PlatformAnalysisAPIView.as_view(), name='admin-platform-analysis'),
    path('invoices/upcoming/', views.UpcomingInvoicesAPIView.as_view(), name='admin-upcoming-invoices'),
]
urlpatterns += router.urls

