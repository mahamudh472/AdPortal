from django.urls import path
from . import views

urlpatterns = [
    # path('daily/', views.AnalysisDailyView.as_view(), name='analysis-daily'),
    path('reports/', views.ReportListView.as_view(), name='report-list'),
    path('generate-report/', views.GenerateReportView.as_view(), name='generate-report'),
]