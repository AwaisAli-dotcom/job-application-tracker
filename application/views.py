from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.db.models import Q
from django.views.decorators.http import require_http_methods

from .models import JobApplication
from .forms import JobApplicationForm


def register(request):
    if request.user.is_authenticated:
        return redirect('application_list')

    if request.method == 'POST':
        form = UserCreationForm(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)

            return redirect('application_list')

    else:
        form = UserCreationForm()

    return render(
        request,
        'registration/register.html',
        {'form': form}
    )


@login_required
def application_list(request):
    applications = JobApplication.objects.filter(user=request.user)
    has_applications = applications.exists()
    search = request.GET.get('search', '').strip()
    selected_status = request.GET.get('status', '').strip()
    valid_statuses = [value for value, label in JobApplication.STATUS_CHOICES]
    selected_sort = request.GET.get('sort', 'newest').strip() or 'newest'
    sort_choices = [
        ('newest', 'Newest first'),
        ('oldest', 'Oldest first'),
        ('updated', 'Recently updated'),
        ('company_az', 'Company A-Z'),
        ('company_za', 'Company Z-A'),
        ('job_title_az', 'Job title A-Z'),
    ]
    sort_options = {
        'newest': '-created_at',
        'oldest': 'created_at',
        'updated': '-updated_at',
        'company_az': 'company',
        'company_za': '-company',
        'job_title_az': 'job_title',
    }

    if selected_sort not in sort_options:
        selected_sort = 'newest'

    if search:
        applications = applications.filter(
            Q(company__icontains=search) |
            Q(job_title__icontains=search) |
            Q(location__icontains=search)
        )

    if selected_status in valid_statuses:
        applications = applications.filter(status=selected_status)

    applications = applications.order_by(sort_options[selected_sort])

    return render(
        request,
        'application/application_list.html',
        {
            'applications': applications,
            'has_applications': has_applications,
            'search': search,
            'selected_status': selected_status,
            'selected_sort': selected_sort,
            'status_choices': JobApplication.STATUS_CHOICES,
            'sort_choices': sort_choices,
        }
    )


@login_required
def application_detail(request, pk):
    job = get_object_or_404(
        JobApplication,
        pk=pk,
        user=request.user
    )

    return render(
        request,
        'application/application_detail.html',
        {'job': job}
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
