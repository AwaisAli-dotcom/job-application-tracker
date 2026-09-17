from django.urls import path
from . import views

urlpatterns = [
    path('accounts/register/', views.register, name='register'),
    path('accounts/profile/', views.profile, name='profile'),
    path('', views.home, name='home'),
    path('about/', views.about, name='about'),
    path('privacy/', views.privacy, name='privacy'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('interviews/', views.interview_list, name='interview_list'),
    path('applications/', views.application_list, name='application_list'),
    path('applications/export/', views.application_export, name='application_export'),
    path('applications/kanban/', views.kanban_board, name='kanban_board'),
    path('applications/<int:pk>/', views.application_detail, name='application_detail'),
    path('applications/<int:pk>/status/', views.update_application_status, name='application_status_update'),
    path('applications/<int:application_pk>/interviews/add/', views.interview_create, name='interview_create'),
    path('applications/<int:application_pk>/documents/add/', views.document_create, name='document_create'),
    path('applications/<int:application_pk>/reminders/add/', views.reminder_create, name='reminder_create'),
    path('documents/<int:pk>/delete/', views.document_delete, name='document_delete'),
    path('interviews/<int:pk>/edit/', views.interview_update, name='interview_update'),
    path('interviews/<int:pk>/delete/', views.interview_delete, name='interview_delete'),
    path('reminders/<int:pk>/edit/', views.reminder_update, name='reminder_update'),
    path('reminders/<int:pk>/delete/', views.reminder_delete, name='reminder_delete'),
    path('add/', views.application_create, name='application_create'),
    path('edit/<int:pk>/', views.application_update, name='application_update'),
    path('delete/<int:pk>/', views.application_delete, name='application_delete'),
]
