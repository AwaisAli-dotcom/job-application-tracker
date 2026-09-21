"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
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
from django.contrib.auth import views as auth_views
from django.contrib.sitemaps.views import sitemap
from django.urls import path, include

from application import auth_views as application_auth_views
from application.seo import PublicSitemap, robots_txt

urlpatterns = [
    path('sitemap.xml', sitemap, {'sitemaps': {'public': PublicSitemap}}, name='sitemap'),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('admin/', admin.site.urls),
    path(
        'accounts/login/',
        auth_views.LoginView.as_view(template_name='registration/login.html'),
        name='login',
    ),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path(
        'accounts/password_change/',
        auth_views.PasswordChangeView.as_view(
            template_name='application/auth/password_change_form.html'
        ),
        name='password_change',
    ),
    path(
        'accounts/password_change/done/',
        auth_views.PasswordChangeDoneView.as_view(
            template_name='application/auth/password_change_done.html'
        ),
        name='password_change_done',
    ),
    path(
        'accounts/password_reset/',
        application_auth_views.RateLimitedPasswordResetView.as_view(
            template_name='application/auth/password_reset_form.html',
            email_template_name='application/auth/password_reset_email.html',
            subject_template_name='application/auth/password_reset_subject.txt',
        ),
        name='password_reset',
    ),
    path(
        'accounts/password_reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='application/auth/password_reset_done.html'
        ),
        name='password_reset_done',
    ),
    path(
        'accounts/reset/<uidb64>/<token>/',
        application_auth_views.RateLimitedPasswordResetConfirmView.as_view(
            template_name='application/auth/password_reset_confirm.html'
        ),
        name='password_reset_confirm',
    ),
    path(
        'accounts/reset/done/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='application/auth/password_reset_complete.html'
        ),
        name='password_reset_complete',
    ),
    path('', include('application.urls')),
]
