from rest_framework import serializers
from .models import AnalysisDaily, Report

class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        fields = ['id', 'name', 'created_at', 'report_type', 'file']