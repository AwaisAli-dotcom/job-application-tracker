from django.contrib import admin
from .models import JobApplication, StatusHistory


admin.site.register(JobApplication)
admin.site.register(StatusHistory)
