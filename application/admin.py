from django.contrib import admin
from .models import ApplicationDocument, Interview, JobApplication, Reminder, StatusHistory


admin.site.register(JobApplication)
admin.site.register(StatusHistory)
admin.site.register(Interview)
admin.site.register(ApplicationDocument)
admin.site.register(Reminder)
