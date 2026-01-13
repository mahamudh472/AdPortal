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
from main.integration_handler import MetaConnect, MetaCallback

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/accounts/', include('accounts.urls')),
    path('api/admin/', include('admin_dashboard.urls')),
    path('api/finance/', include('finance.urls')),
    path('api/main/', include('main.urls')),
    path('api/auth/meta/connect/', MetaConnect.as_view()),
    path('api/auth/meta/callback/', MetaCallback.as_view())

]
