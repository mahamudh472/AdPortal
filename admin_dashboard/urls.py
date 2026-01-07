from django.urls import path
from . import views

urlpatterns = [
	path('dashboard/', views.DashboardAPIView.as_view()),
	path('campaigns/', views.CampaignListAPIView.as_view()),
	path('user-management/', views.UserManagementAPIView.as_view()),
	path('user-management-list/', views.UserManagementListAPIView.as_view())
]