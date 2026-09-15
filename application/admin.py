from django.contrib import admin
from .models import Interview, JobApplication, StatusHistory


admin.site.register(JobApplication)
admin.site.register(StatusHistory)
admin.site.register(Interview)
