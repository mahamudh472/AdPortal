from django.urls import path
from . import views
from .integration_handler import AdProfileListView, SelectAdProfileView

urlpatterns = [
    path('organization/', views.OrganizationRetrieveUpdateAPIView.as_view()),
	path('campaigns/', views.CampaignListAPIView.as_view()),
	path('create-ad/', views.CreateAdAPIView.as_view()),
	path('get-ad-profiles/', AdProfileListView.as_view()),
	path('select-ad-profile/', SelectAdProfileView.as_view()),
	path('generate-ai-copy/', views.AICopyGeneratorAPIView.as_view()),
	path('analytics/', views.AnalyticsAPIView.as_view()),
	path('create-platform-campaign/', views.CreatePlatformCampaignAPIView.as_view()),
    path('team/', views.TeamAPIView.as_view()),
    path('team-members/', views.TeamMemberListAPIView.as_view()),
    path('team-member/<str:id>/', views.UpdateDeleteTeamMemberAPIView.as_view()),
]