from django.urls import path
from . import views

urlpatterns = [
	path('dashboard/', views.DashboardAPIView.as_view()),
	path('campaigns/', views.CampaignListAPIView.as_view()),
	path('user-management/', views.UserManagementAPIView.as_view()),
	path('user-management-list/', views.UserManagementListAPIView.as_view()),
    path('user-management/<uuid:id>/', views.ChangeUserStatusAPIView.as_view()),
    path('organizations/', views.OrganizationListAPIView.as_view()),
    path('transactions/', views.TransactionListAPIView.as_view()),
    path('notification-settings/', views.AdminNotificationSettingsAPIView.as_view()),
    path('reports/', views.AdminReportListView.as_view(), name='admin-report-list'),
    path('generate-report/', views.GenerateAdminReportView.as_view(), name='admin-generate-report'),
    path('finance/', views.FinanceOverviewAPIView.as_view(), name='admin-finance-overview'),
]
