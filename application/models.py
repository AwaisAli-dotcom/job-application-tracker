from urllib.parse import urlsplit

from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone


def validate_company_name(value):
    value = value.strip()

    if not value:
        raise ValidationError('Company name is required.')

    if len(value) < 2:
        raise ValidationError('Company name must be at least 2 characters.')


def validate_job_title(value):
    value = value.strip()

    if not value:
        raise ValidationError('Job title is required.')

    if len(value) < 2:
        raise ValidationError('Job title must be at least 2 characters.')


class JobApplication(models.Model):

    STATUS_CHOICES = [
        ('saved', 'Saved'),
        ('applied', 'Applied'),
        ('interview', 'Interview'),
        ('technical_test', 'Technical Test'),
        ('offer', 'Offer'),
        ('rejected', 'Rejected'),
        ('withdrawn', 'Withdrawn'),
    ]

    JOB_TYPE_CHOICES = [
        ('full_time', 'Full-time'),
        ('part_time', 'Part-time'),
        ('internship', 'Internship'),
        ('contract', 'Contract'),
        ('temporary', 'Temporary'),
        ('remote', 'Remote'),
    ]

    WORK_MODE_CHOICES = [
        ('onsite', 'On-site'),
        ('hybrid', 'Hybrid'),
        ('remote', 'Remote'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='job_applications'
    )

    company = models.CharField(
        max_length=120,
        validators=[validate_company_name],
    )
    job_title = models.CharField(
        max_length=160,
        validators=[validate_job_title],
    )

    location = models.CharField(
        max_length=150,
        blank=True
    )

    job_url = models.URLField(
        blank=True
    )

    employment_type = models.CharField(
        max_length=20,
        choices=JOB_TYPE_CHOICES,
        blank=True
    )

    work_mode = models.CharField(
        max_length=20,
        choices=WORK_MODE_CHOICES,
        blank=True
    )

    source = models.CharField(
        max_length=80,
        blank=True
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='saved'
    )

    salary = models.CharField(
        max_length=100,
        blank=True
    )

    salary_min = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True
    )

    salary_max = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True
    )

    currency = models.CharField(
        max_length=3,
        default='EUR'
    )

    application_date = models.DateField(
        null=True,
        blank=False,
        error_messages={
            'blank': 'Application date is required.',
        },
    )

    deadline = models.DateField(
        null=True,
        blank=True
    )

    notes = models.TextField(
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(salary_min__gte=0) | models.Q(salary_min__isnull=True),
                name='application_salary_min_nonnegative',
            ),
            models.CheckConstraint(
                condition=models.Q(salary_max__gte=0) | models.Q(salary_max__isnull=True),
                name='application_salary_max_nonnegative',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(salary_min__isnull=True)
                    | models.Q(salary_max__isnull=True)
                    | models.Q(salary_max__gte=models.F('salary_min'))
                ),
                name='application_salary_range_valid',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(application_date__isnull=True)
                    | models.Q(deadline__isnull=True)
                    | models.Q(deadline__gte=models.F('application_date'))
                ),
                name='application_deadline_not_before_date',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        self.company = (self.company or '').strip()
        self.job_title = (self.job_title or '').strip()

        if self.job_url and urlsplit(self.job_url).scheme.lower() not in {'http', 'https'}:
            errors['job_url'] = 'Enter a valid job URL using http:// or https://.'

        if self.application_date and self.application_date > timezone.localdate():
            errors['application_date'] = 'Application date cannot be in the future.'

        if self.salary_min is not None and self.salary_min < 0:
            errors['salary_min'] = 'Salary minimum cannot be negative.'

        if self.salary_max is not None and self.salary_max < 0:
            errors['salary_max'] = 'Salary maximum cannot be negative.'

        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_max < self.salary_min
        ):
            errors['salary_max'] = 'Salary maximum must be greater than or equal to salary minimum.'

        if self.application_date and self.deadline and self.deadline < self.application_date:
            errors['deadline'] = 'Deadline cannot be before the application date.'

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.company} - {self.job_title}"


class StatusHistory(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='status_history'
    )
    application = models.ForeignKey(
        JobApplication,
        on_delete=models.CASCADE,
        related_name='status_history'
    )
    old_status = models.CharField(
        max_length=20,
        choices=JobApplication.STATUS_CHOICES
    )
    new_status = models.CharField(
        max_length=20,
        choices=JobApplication.STATUS_CHOICES
    )
    changed_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ['-changed_at']

    def __str__(self):
        return f"{self.application} moved from {self.old_status} to {self.new_status}"

    def clean(self):
        super().clean()

        if self.application_id and self.user_id and self.application.user_id != self.user_id:
            raise ValidationError({'user': 'Status history owner must match the application owner.'})

        if self.old_status == self.new_status:
            raise ValidationError({'new_status': 'The new status must be different.'})


class Interview(models.Model):
    INTERVIEW_TYPE_CHOICES = [
        ('hr_screen', 'HR Screen'),
        ('hiring_manager', 'Hiring Manager'),
        ('technical', 'Technical'),
        ('take_home_review', 'Take-home Review'),
        ('final', 'Final'),
        ('other', 'Other'),
    ]

    MODE_CHOICES = [
        ('video', 'Video'),
        ('phone', 'Phone'),
        ('onsite', 'On-site'),
        ('other', 'Other'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='interviews'
    )
    application = models.ForeignKey(
        JobApplication,
        on_delete=models.CASCADE,
        related_name='interviews'
    )
    interview_type = models.CharField(
        max_length=30,
        choices=INTERVIEW_TYPE_CHOICES,
        default='hr_screen'
    )
    mode = models.CharField(
        max_length=20,
        choices=MODE_CHOICES,
        default='video'
    )
    scheduled_at = models.DateTimeField()
    interviewer = models.CharField(
        max_length=150,
        blank=True
    )
    location_or_link = models.CharField(
        max_length=255,
        blank=True
    )
    outcome = models.CharField(
        max_length=150,
        blank=True
    )
    notes = models.TextField(
        blank=True
    )
    created_at = models.DateTimeField(
        auto_now_add=True
    )
    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ['scheduled_at']

    def __str__(self):
        return f"{self.application} interview on {self.scheduled_at}"

    def clean(self):
        super().clean()

        if self.application_id and self.user_id and self.application.user_id != self.user_id:
            raise ValidationError({'user': 'Interview owner must match the application owner.'})


class ApplicationDocument(models.Model):
    DOCUMENT_TYPE_CHOICES = [
        ('cv', 'CV'),
        ('cover_letter', 'Cover Letter'),
        ('portfolio', 'Portfolio'),
        ('other', 'Other'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='application_documents'
    )
    application = models.ForeignKey(
        JobApplication,
        on_delete=models.CASCADE,
        related_name='documents'
    )
    title = models.CharField(max_length=150)
    document_type = models.CharField(
        max_length=30,
        choices=DOCUMENT_TYPE_CHOICES,
        default='cv'
    )
    link = models.URLField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()

        if self.application_id and self.user_id and self.application.user_id != self.user_id:
            raise ValidationError({'user': 'Document owner must match the application owner.'})


class Reminder(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reminders'
    )
    application = models.ForeignKey(
        JobApplication,
        on_delete=models.CASCADE,
        related_name='reminders'
    )
    title = models.CharField(max_length=150)
    due_at = models.DateTimeField()
    completed = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['completed', 'due_at']

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()

        if self.application_id and self.user_id and self.application.user_id != self.user_id:
            raise ValidationError({'user': 'Reminder owner must match the application owner.'})
