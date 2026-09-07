from django.urls import path
from . import views

urlpatterns = [
    path('accounts/register/', views.register, name='register'),
    path('', views.application_list, name='application_list'),
    path('applications/<int:pk>/', views.application_detail, name='application_detail'),
    path('add/', views.application_create, name='application_create'),
    path('edit/<int:pk>/', views.application_update, name='application_update'),
    path('delete/<int:pk>/', views.application_delete, name='application_delete'),
]
