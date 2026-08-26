from django.urls import path
from . import views

urlpatterns = [
    path('', views.application_list, name='application_list'),
]