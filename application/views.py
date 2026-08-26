from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

from .models import JobApplication
from .forms import JobApplicationForm


@login_required
def application_list(request):
    applications = JobApplication.objects.filter(user=request.user)

    return render(
        request,
        'application/application_list.html',
        {'applications': applications}
    )


@login_required
def application_create(request):
    if request.method == 'POST':
        form = JobApplicationForm(request.POST)

        if form.is_valid():
            job = form.save(commit=False)
            job.user = request.user
            job.save()

            return redirect('application_list')

    else:
        form = JobApplicationForm()

    return render(
        request,
        'application/application_form.html',
        {'form': form}
    )