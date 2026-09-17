import csv
from collections import Counter
from datetime import date

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.csrf import requires_csrf_token

from .models import ApplicationDocument, Interview, JobApplication, Reminder, StatusHistory
from .forms import (
    ApplicationDocumentForm,
    InterviewForm,
    JobApplicationForm,
    ProfileForm,
    RegistrationForm,
    ReminderForm,
)


def home(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    return render(request, 'application/home.html')


def about(request):
    return render(request, 'application/about.html')


def privacy(request):
    return render(request, 'application/privacy.html')


@requires_csrf_token
def csrf_failure(request, reason=''):
    return render(request, '403.html', status=403)


def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = RegistrationForm(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Your account has been created.')

            return redirect('dashboard')

    else:
        form = RegistrationForm()

    return render(
        request,
        'registration/register.html',
        {'form': form}
    )


@login_required
def profile(request):
    if request.method == 'POST':
        form = ProfileForm(request.POST, instance=request.user)

        if form.is_valid():
            form.save()
            messages.success(request, 'Your account details have been updated.')

            return redirect('profile')

    else:
        form = ProfileForm(instance=request.user)

    return render(request, 'registration/profile.html', {'form': form})


def csv_safe(value):
    text = '' if value is None else str(value)

    if text.startswith(('=', '+', '-', '@')):
        return f"'{text}"

    return text


@login_required
def application_export(request):
    applications = JobApplication.objects.filter(user=request.user).order_by('-created_at')
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="job-applications.csv"'
    writer = csv.writer(response)
    writer.writerow([
        'Company',
        'Job title',
        'Location',
        'Job URL',
        'Employment type',
        'Work mode',
        'Source',
        'Status',
        'Salary',
        'Salary minimum',
        'Salary maximum',
        'Currency',
        'Application date',
        'Deadline',
        'Notes',
        'Created',
        'Updated',
    ])

    for job in applications:
        writer.writerow([
            csv_safe(job.company),
            csv_safe(job.job_title),
            csv_safe(job.location),
            csv_safe(job.job_url),
            job.get_employment_type_display(),
            job.get_work_mode_display(),
            csv_safe(job.source),
            job.get_status_display(),
            csv_safe(job.salary),
            job.salary_min if job.salary_min is not None else '',
            job.salary_max if job.salary_max is not None else '',
            csv_safe(job.currency),
            job.application_date.isoformat() if job.application_date else '',
            job.deadline.isoformat() if job.deadline else '',
            csv_safe(job.notes),
            timezone.localtime(job.created_at).isoformat(),
            timezone.localtime(job.updated_at).isoformat(),
        ])

    return response


def record_status_change(job, old_status, new_status):
    if old_status == new_status:
        return

    StatusHistory.objects.create(
        user=job.user,
        application=job,
        old_status=old_status,
        new_status=new_status
    )


@login_required
def dashboard(request):
    applications = JobApplication.objects.filter(user=request.user)
    submitted_applications = applications.exclude(status='saved')
    interviewing_statuses = ['interview', 'technical_test']
    response_statuses = ['interview', 'technical_test', 'offer', 'rejected']
    active_statuses = ['saved', 'applied', 'interview', 'technical_test', 'offer']

    total_applications = applications.count()
    submitted_count = submitted_applications.count()
    interviews_count = applications.filter(status__in=interviewing_statuses).count()
    reached_interview_count = submitted_applications.filter(
        Q(status__in=interviewing_statuses)
        | Q(
            status_history__user=request.user,
            status_history__new_status__in=interviewing_statuses,
        )
        | Q(interviews__user=request.user)
    ).distinct().count()
    offers_count = submitted_applications.filter(
        Q(status='offer')
        | Q(status_history__user=request.user, status_history__new_status='offer')
    ).distinct().count()
    response_count = submitted_applications.filter(
        Q(status__in=response_statuses)
        | Q(
            status_history__user=request.user,
            status_history__new_status__in=response_statuses,
        )
        | Q(interviews__user=request.user)
    ).distinct().count()
    active_count = applications.filter(status__in=active_statuses).count()
    rejected_count = applications.filter(status='rejected').count()
    withdrawn_count = applications.filter(status='withdrawn').count()
    interview_rate = round((reached_interview_count / submitted_count) * 100) if submitted_count else 0
    offer_rate = round((offers_count / submitted_count) * 100) if submitted_count else 0
    response_rate = round((response_count / submitted_count) * 100) if submitted_count else 0

    current_month = timezone.localdate().replace(day=1)
    applied_this_month = submitted_applications.filter(
        application_date__year=current_month.year,
        application_date__month=current_month.month,
    ).count()
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
    upcoming_interviews = Interview.objects.filter(
        user=request.user,
        application__user=request.user,
        scheduled_at__gte=timezone.now()
    ).select_related('application').order_by('scheduled_at')[:5]
    upcoming_reminders = Reminder.objects.filter(
        user=request.user,
        application__user=request.user,
        completed=False,
        due_at__gte=timezone.now()
    ).select_related('application').order_by('due_at')[:5]
    upcoming_deadlines = applications.filter(
        deadline__gte=timezone.localdate()
    ).order_by('deadline')[:5]

    return render(
        request,
        'application/dashboard.html',
        {
            'total_applications': total_applications,
            'submitted_count': submitted_count,
            'applied_this_month': applied_this_month,
            'interviews_count': interviews_count,
            'offers_count': offers_count,
            'active_count': active_count,
            'rejected_count': rejected_count,
            'withdrawn_count': withdrawn_count,
            'interview_rate': interview_rate,
            'offer_rate': offer_rate,
            'response_rate': response_rate,
            'recent_applications': applications.order_by('-updated_at')[:5],
            'monthly_chart': monthly_chart,
            'max_monthly_count': max_monthly_count,
            'status_chart': status_chart,
            'max_status_count': max_status_count,
            'upcoming_interviews': upcoming_interviews,
            'upcoming_reminders': upcoming_reminders,
            'upcoming_deadlines': upcoming_deadlines,
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
        JobApplication.objects.prefetch_related(
            Prefetch('interviews', queryset=Interview.objects.filter(user=request.user)),
            Prefetch('documents', queryset=ApplicationDocument.objects.filter(user=request.user)),
            Prefetch('reminders', queryset=Reminder.objects.filter(user=request.user)),
            Prefetch('status_history', queryset=StatusHistory.objects.filter(user=request.user)),
        ),
        pk=pk,
        user=request.user
    )

    return render(
        request,
        'application/application_detail.html',
        {'job': job}
    )


@login_required
def interview_list(request):
    interviews = Interview.objects.filter(
        user=request.user,
        application__user=request.user,
    ).select_related('application')
    now = timezone.now()

    return render(
        request,
        'application/interview_list.html',
        {
            'upcoming_interviews': interviews.filter(scheduled_at__gte=now).order_by('scheduled_at'),
            'past_interviews': interviews.filter(scheduled_at__lt=now).order_by('-scheduled_at'),
        }
    )


@login_required
def interview_create(request, application_pk):
    application = get_object_or_404(
        JobApplication,
        pk=application_pk,
        user=request.user
    )

    if request.method == 'POST':
        form = InterviewForm(request.POST)

        if form.is_valid():
            interview = form.save(commit=False)
            interview.user = request.user
            interview.application = application
            interview.save()
            messages.success(request, 'Interview added.')

            return redirect('application_detail', pk=application.pk)

    else:
        form = InterviewForm()

    return render(
        request,
        'application/interview_form.html',
        {
            'form': form,
            'application': application,
        }
    )


@login_required
def interview_update(request, pk):
    interview = get_object_or_404(
        Interview.objects.select_related('application'),
        pk=pk,
        user=request.user,
        application__user=request.user,
    )

    if request.method == 'POST':
        form = InterviewForm(request.POST, instance=interview)

        if form.is_valid():
            form.save()
            messages.success(request, 'Interview updated.')

            return redirect('application_detail', pk=interview.application.pk)

    else:
        form = InterviewForm(instance=interview)

    return render(
        request,
        'application/interview_form.html',
        {
            'form': form,
            'application': interview.application,
            'interview': interview,
        }
    )


@login_required
@require_http_methods(['GET', 'POST'])
def interview_delete(request, pk):
    interview = get_object_or_404(
        Interview.objects.select_related('application'),
        pk=pk,
        user=request.user,
        application__user=request.user,
    )

    if request.method == 'POST':
        application_pk = interview.application.pk
        interview.delete()
        messages.success(request, 'Interview deleted.')

        return redirect('application_detail', pk=application_pk)

    return render(
        request,
        'application/interview_confirm_delete.html',
        {'interview': interview}
    )


@login_required
def document_create(request, application_pk):
    application = get_object_or_404(
        JobApplication,
        pk=application_pk,
        user=request.user
    )

    if request.method == 'POST':
        form = ApplicationDocumentForm(request.POST)

        if form.is_valid():
            document = form.save(commit=False)
            document.user = request.user
            document.application = application
            document.save()
            messages.success(request, 'Document added.')

            return redirect('application_detail', pk=application.pk)

    else:
        form = ApplicationDocumentForm()

    return render(
        request,
        'application/document_form.html',
        {
            'form': form,
            'application': application,
        }
    )


@login_required
@require_http_methods(['GET', 'POST'])
def document_delete(request, pk):
    document = get_object_or_404(
        ApplicationDocument.objects.select_related('application'),
        pk=pk,
        user=request.user,
        application__user=request.user,
    )

    if request.method == 'POST':
        application_pk = document.application.pk
        document.delete()
        messages.success(request, 'Document deleted.')

        return redirect('application_detail', pk=application_pk)

    return render(
        request,
        'application/document_confirm_delete.html',
        {'document': document}
    )


@login_required
def document_update(request, pk):
    document = get_object_or_404(
        ApplicationDocument.objects.select_related('application'),
        pk=pk,
        user=request.user,
        application__user=request.user,
    )

    if request.method == 'POST':
        form = ApplicationDocumentForm(request.POST, instance=document)

        if form.is_valid():
            form.save()
            messages.success(request, 'Document updated.')

            return redirect('application_detail', pk=document.application.pk)

    else:
        form = ApplicationDocumentForm(instance=document)

    return render(
        request,
        'application/document_form.html',
        {
            'form': form,
            'application': document.application,
            'document': document,
        }
    )


@login_required
def reminder_create(request, application_pk):
    application = get_object_or_404(
        JobApplication,
        pk=application_pk,
        user=request.user
    )

    if request.method == 'POST':
        form = ReminderForm(request.POST)

        if form.is_valid():
            reminder = form.save(commit=False)
            reminder.user = request.user
            reminder.application = application
            reminder.save()
            messages.success(request, 'Reminder added.')

            return redirect('application_detail', pk=application.pk)

    else:
        form = ReminderForm()

    return render(
        request,
        'application/reminder_form.html',
        {
            'form': form,
            'application': application,
        }
    )


@login_required
def reminder_update(request, pk):
    reminder = get_object_or_404(
        Reminder.objects.select_related('application'),
        pk=pk,
        user=request.user,
        application__user=request.user,
    )

    if request.method == 'POST':
        form = ReminderForm(request.POST, instance=reminder)

        if form.is_valid():
            form.save()
            messages.success(request, 'Reminder updated.')

            return redirect('application_detail', pk=reminder.application.pk)

    else:
        form = ReminderForm(instance=reminder)

    return render(
        request,
        'application/reminder_form.html',
        {
            'form': form,
            'application': reminder.application,
            'reminder': reminder,
        }
    )


@login_required
@require_http_methods(['GET', 'POST'])
def reminder_delete(request, pk):
    reminder = get_object_or_404(
        Reminder.objects.select_related('application'),
        pk=pk,
        user=request.user,
        application__user=request.user,
    )

    if request.method == 'POST':
        application_pk = reminder.application.pk
        reminder.delete()
        messages.success(request, 'Reminder deleted.')

        return redirect('application_detail', pk=application_pk)

    return render(
        request,
        'application/reminder_confirm_delete.html',
        {'reminder': reminder}
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

    try:
        with transaction.atomic():
            old_status = job.status
            job.status = new_status
            job.full_clean()
            job.save(update_fields=['status', 'updated_at'])
            record_status_change(job, old_status, new_status)
    except ValidationError as error:
        error_message = next(iter(error.message_dict.values()))[0]

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'ok': False, 'error': error_message}, status=400)

        messages.error(request, error_message)
        return redirect('kanban_board')

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse(
            {
                'ok': True,
                'status': job.status,
                'status_label': job.get_status_display(),
            }
        )

    messages.success(request, 'Application status updated.')
    return redirect('kanban_board')


@login_required
def application_create(request):
    if request.method == 'POST':
        form = JobApplicationForm(request.POST)

        if form.is_valid():
            job = form.save(commit=False)
            job.user = request.user
            job.save()
            messages.success(request, 'Application added.')

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
        old_status = job.status
        form = JobApplicationForm(request.POST, instance=job)

        if form.is_valid():
            with transaction.atomic():
                job = form.save()
                record_status_change(job, old_status, job.status)
            messages.success(request, 'Application updated.')

            return redirect('application_list')

    else:
        form = JobApplicationForm(instance=job)

    return render(
        request,
        'application/application_form.html',
        {'form': form, 'job': job}
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
        messages.success(request, 'Application deleted.')
        return redirect('application_list')

    return render(
        request,
        'application/application_confirm_delete.html',
        {'job': job}
    )
