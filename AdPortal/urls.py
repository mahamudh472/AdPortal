"""
URL configuration for AdPortal project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from main.integration_handler import MetaConnect, MetaCallback, TikTokCallback, TikTokConnect

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/accounts/', include('accounts.urls')),
    path('api/v1/admin/', include('admin_dashboard.urls')),
    path('api/v1/finance/', include('finance.urls')),
    path('api/v1/main/', include('main.urls')),
    path('api/v1/auth/meta/connect/', MetaConnect.as_view()),
    path('api/v1/auth/meta/callback/', MetaCallback.as_view()),
    path('api/v1/auth/tiktok/connect/', TikTokConnect.as_view()),
    path('api/v1/auth/tiktok/callback/', TikTokCallback.as_view()),

    path('silk/', include('silk.urls', namespace='silk')),

]
