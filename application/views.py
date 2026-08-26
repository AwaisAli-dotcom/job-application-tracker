from django.shortcuts import render
from .models import JobApplication


def application_list(request):
    applications = JobApplication.objects.all()

    return render(
        request,
        'application/application_list.html',
        {'applications': applications}
    )