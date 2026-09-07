from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods

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


@login_required
def application_update(request, pk):
    job = get_object_or_404(
        JobApplication,
        pk=pk,
        user=request.user
    )

    if request.method == 'POST':
        form = JobApplicationForm(request.POST, instance=job)

        if form.is_valid():
            form.save()

            return redirect('application_list')

    else:
        form = JobApplicationForm(instance=job)

    return render(
        request,
        'application/application_form.html',
        {'form': form}
    )


@login_required
@require_http_methods(['GET', 'POST'])
def application_delete(request, pk):
    job = get_object_or_404(
        JobApplication,
        pk=pk,
        user=request.user
    )

    if request.method == 'POST':
        job.delete()
        return redirect('application_list')

    return render(
        request,
        'application/application_confirm_delete.html',
        {'job': job}
    )
