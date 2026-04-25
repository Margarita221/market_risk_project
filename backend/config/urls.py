"""
URL configuration for config project.

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
from django.urls import include, path
from django.contrib.auth.views import LogoutView

from riskapp.views import (
    LocalizedLoginView,
    LocalizedPasswordChangeDoneView,
    LocalizedPasswordChangeView,
    LocalizedPasswordResetCompleteView,
    LocalizedPasswordResetConfirmView,
    LocalizedPasswordResetDoneView,
    LocalizedPasswordResetView,
)

urlpatterns = [
    path('', include('riskapp.urls')),
    path('accounts/login/', LocalizedLoginView.as_view(), name='login'),
    path('accounts/logout/', LogoutView.as_view(), name='logout'),
    path('accounts/password-change/', LocalizedPasswordChangeView.as_view(), name='account_password_change'),
    path('accounts/password-change/done/', LocalizedPasswordChangeDoneView.as_view(), name='account_password_change_done'),
    path('accounts/password-reset/', LocalizedPasswordResetView.as_view(), name='account_password_reset'),
    path('accounts/password-reset/done/', LocalizedPasswordResetDoneView.as_view(), name='account_password_reset_done'),
    path('accounts/reset/<uidb64>/<token>/', LocalizedPasswordResetConfirmView.as_view(), name='account_password_reset_confirm'),
    path('accounts/reset/done/', LocalizedPasswordResetCompleteView.as_view(), name='account_password_reset_complete'),
    path('admin/', admin.site.urls),
]
