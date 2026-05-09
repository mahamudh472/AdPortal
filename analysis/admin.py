from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import AnalysisDaily

@admin.register(AnalysisDaily)
class AnalysisDailyAdmin(ModelAdmin):
    pass
