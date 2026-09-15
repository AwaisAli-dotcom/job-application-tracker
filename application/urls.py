from django.urls import path
from . import views

urlpatterns = [
    path('accounts/register/', views.register, name='register'),
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('applications/', views.application_list, name='application_list'),
    path('applications/kanban/', views.kanban_board, name='kanban_board'),
    path('applications/<int:pk>/', views.application_detail, name='application_detail'),
    path('applications/<int:pk>/status/', views.update_application_status, name='application_status_update'),
    path('add/', views.application_create, name='application_create'),
    path('edit/<int:pk>/', views.application_update, name='application_update'),
    path('delete/<int:pk>/', views.application_delete, name='application_delete'),
]
