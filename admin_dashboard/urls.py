from django.urls import path
from . import views

urlpatterns = [
	path('dashboard/', views.DashboardAPIView.as_view()),
]