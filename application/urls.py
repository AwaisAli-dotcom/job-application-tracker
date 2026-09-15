from django.urls import path
from . import views

urlpatterns = [
    path('accounts/register/', views.register, name='register'),
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('interviews/', views.interview_list, name='interview_list'),
    path('applications/', views.application_list, name='application_list'),
    path('applications/kanban/', views.kanban_board, name='kanban_board'),
    path('applications/<int:pk>/', views.application_detail, name='application_detail'),
    path('applications/<int:pk>/status/', views.update_application_status, name='application_status_update'),
    path('applications/<int:application_pk>/interviews/add/', views.interview_create, name='interview_create'),
    path('interviews/<int:pk>/edit/', views.interview_update, name='interview_update'),
    path('interviews/<int:pk>/delete/', views.interview_delete, name='interview_delete'),
    path('add/', views.application_create, name='application_create'),
    path('edit/<int:pk>/', views.application_update, name='application_update'),
    path('delete/<int:pk>/', views.application_delete, name='application_delete'),
]
