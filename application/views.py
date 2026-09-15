from collections import Counter
from datetime import date

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods, require_POST

from .models import JobApplication
from .forms import JobApplicationForm


def home(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    return render(request, 'application/home.html')


def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = UserCreationForm(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)

            return redirect('dashboard')

    else:
        form = UserCreationForm()

    return render(
        request,
        'registration/register.html',
        {'form': form}
    )


@login_required
def dashboard(request):
    applications = JobApplication.objects.filter(user=request.user)
    submitted_applications = applications.exclude(status='saved')
    interviewing_statuses = ['interview', 'technical_test']
    active_statuses = ['saved', 'applied', 'interview', 'technical_test', 'offer']

    total_applications = applications.count()
    submitted_count = submitted_applications.count()
    interviews_count = applications.filter(status__in=interviewing_statuses).count()
    offers_count = applications.filter(status='offer').count()
    active_count = applications.filter(status__in=active_statuses).count()
    rejected_count = applications.filter(status='rejected').count()
    withdrawn_count = applications.filter(status='withdrawn').count()
    interview_rate = round((interviews_count / submitted_count) * 100) if submitted_count else 0
    offer_rate = round((offers_count / submitted_count) * 100) if submitted_count else 0

    current_month = timezone.localdate().replace(day=1)
    month_starts = []
    year = current_month.year
    month = current_month.month

    for _ in range(6):
        month_starts.append(date(year, month, 1))
        month -= 1

        if month == 0:
            month = 12
            year -= 1

    month_starts.reverse()
    month_counts = Counter(
        application_date.replace(day=1)
        for application_date in applications.exclude(application_date__isnull=True)
        .values_list('application_date', flat=True)
    )
    monthly_chart = [
        {
            'label': month_start.strftime('%b %Y'),
            'count': month_counts.get(month_start, 0),
        }
        for month_start in month_starts
    ]
    max_monthly_count = max([item['count'] for item in monthly_chart] + [1])

    status_counts = applications.values_list('status', flat=True)
    status_counter = Counter(status_counts)
    status_chart = [
        {
            'value': value,
            'label': label,
            'count': status_counter.get(value, 0),
        }
        for value, label in JobApplication.STATUS_CHOICES
    ]
    max_status_count = max([item['count'] for item in status_chart] + [1])

    return render(
        request,
        'application/dashboard.html',
        {
            'total_applications': total_applications,
            'submitted_count': submitted_count,
            'interviews_count': interviews_count,
            'offers_count': offers_count,
            'active_count': active_count,
            'rejected_count': rejected_count,
            'withdrawn_count': withdrawn_count,
            'interview_rate': interview_rate,
            'offer_rate': offer_rate,
            'recent_applications': applications.order_by('-updated_at')[:5],
            'monthly_chart': monthly_chart,
            'max_monthly_count': max_monthly_count,
            'status_chart': status_chart,
            'max_status_count': max_status_count,
        }
    )


@login_required
def application_list(request):
    applications = JobApplication.objects.filter(user=request.user)
    has_applications = applications.exists()
    search = request.GET.get('search', '').strip()
    selected_status = request.GET.get('status', '').strip()
    selected_employment_type = request.GET.get('employment_type', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    valid_statuses = [value for value, label in JobApplication.STATUS_CHOICES]
    valid_employment_types = [value for value, label in JobApplication.JOB_TYPE_CHOICES]
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

    if selected_employment_type in valid_employment_types:
        applications = applications.filter(employment_type=selected_employment_type)

    parsed_date_from = parse_date(date_from) if date_from else None
    parsed_date_to = parse_date(date_to) if date_to else None

    if parsed_date_from:
        applications = applications.filter(application_date__gte=parsed_date_from)

    if parsed_date_to:
        applications = applications.filter(application_date__lte=parsed_date_to)

    applications = applications.order_by(sort_options[selected_sort])
    paginator = Paginator(applications, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    query_params = request.GET.copy()
    query_params.pop('page', None)
    pagination_query = query_params.urlencode()
    page_prefix = f'{pagination_query}&' if pagination_query else ''

    return render(
        request,
        'application/application_list.html',
        {
            'applications': page_obj,
            'has_applications': has_applications,
            'page_obj': page_obj,
            'page_prefix': page_prefix,
            'search': search,
            'selected_status': selected_status,
            'selected_employment_type': selected_employment_type,
            'date_from': date_from,
            'date_to': date_to,
            'selected_sort': selected_sort,
            'status_choices': JobApplication.STATUS_CHOICES,
            'employment_type_choices': JobApplication.JOB_TYPE_CHOICES,
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
def kanban_board(request):
    applications = JobApplication.objects.filter(user=request.user).order_by('-updated_at')
    columns = []

    for value, label in JobApplication.STATUS_CHOICES:
        column_applications = [job for job in applications if job.status == value]
        columns.append(
            {
                'value': value,
                'label': label,
                'applications': column_applications,
                'count': len(column_applications),
            }
        )

    return render(
        request,
        'application/kanban.html',
        {
            'columns': columns,
            'status_choices': JobApplication.STATUS_CHOICES,
        }
    )


@login_required
@require_POST
def update_application_status(request, pk):
    job = get_object_or_404(
        JobApplication,
        pk=pk,
        user=request.user
    )
    new_status = request.POST.get('status', '').strip()
    valid_statuses = [value for value, label in JobApplication.STATUS_CHOICES]

    if new_status not in valid_statuses:
        return JsonResponse(
            {'ok': False, 'error': 'Invalid status.'},
            status=400
        )

    job.status = new_status
    job.save(update_fields=['status', 'updated_at'])

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse(
            {
                'ok': True,
                'status': job.status,
                'status_label': job.get_status_display(),
            }
        )

    return redirect('kanban_board')


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
