from django.urls import path
from . import views
from .integration_handler import AdProfileListView, SelectAdProfileView, MetaPageListView, SelectMetaPageView

urlpatterns = [
    path('dashboard/', views.DashboardAPIView.as_view()),
    path('organization/', views.OrganizationRetrieveUpdateAPIView.as_view()),
    path('integrations-status/', views.IntegrationStatusAPIView.as_view()),
	path('campaigns/', views.CampaignListAPIView.as_view()),
    path('campaign/<int:id>/', views.CampaignRetrieveUpdateDestroyAPIView.as_view()),
	path('create-ad/', views.CreateAdAPIView.as_view()),
    path('update-ad/', views.CreateAdAPIView.as_view()),
	path('get-ad-profiles/', AdProfileListView.as_view()),
	path('select-ad-profile/', SelectAdProfileView.as_view()),
	path('get-meta-pages/', MetaPageListView.as_view()),
	path('select-meta-page/', SelectMetaPageView.as_view()),
	path('generate-ai-copy/', views.AICopyGeneratorAPIView.as_view()),
    path('generate-ad-copy/', views.AIAdCopyGeneratorAPIView.as_view()),
    path('ai-insights/', views.AIInsightListAPIView.as_view()),
	path('analytics/', views.AnalyticsAPIView.as_view()),
	path('create-platform-campaign/', views.CreatePlatformCampaignAPIView.as_view()),
    path('team/', views.TeamAPIView.as_view()),
    path('team-members/', views.TeamMemberListAPIView.as_view()),
    path('team-member/<str:id>/', views.UpdateDeleteTeamMemberAPIView.as_view()),
	path('invite-team-member/', views.TeamInvitationAPIView.as_view()),
    path('accept-invitation/<str:token>/', views.InvitationAcceptAPIView.as_view()),


    path('sync-ads/', views.SyncAdsAPIView.as_view()),

    # Meta ad management — test endpoints
    path('meta/create-ad/', views.MetaCreateAdTestAPIView.as_view()),
    path('meta/update-campaign/', views.MetaUpdateCampaignTestAPIView.as_view()),
    path('meta/delete-ad/', views.MetaDeleteAdTestAPIView.as_view()),
]
