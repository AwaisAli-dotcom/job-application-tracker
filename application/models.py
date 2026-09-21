from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator, RegexValidator
from django.utils import timezone


MAX_DOCUMENT_FILE_SIZE = 4 * 1024 * 1024
DOCUMENT_CONTENT_TYPES = {
    '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.jpeg': 'image/jpeg',
    '.jpg': 'image/jpeg',
    '.odt': 'application/vnd.oasis.opendocument.text',
    '.pdf': 'application/pdf',
    '.png': 'image/png',
    '.rtf': 'application/rtf',
    '.txt': 'text/plain',
}


def document_content_type(filename):
    return DOCUMENT_CONTENT_TYPES.get(Path(filename).suffix.lower(), 'application/octet-stream')


def document_upload_path(instance, filename):
    extension = Path(filename).suffix.lower()
    return (
        f'documents/user_{instance.user_id}/application_{instance.application_id}/'
        f'{uuid4().hex}{extension}'
    )


def validate_document_file(uploaded_file):
    extension = Path(uploaded_file.name).suffix.lower()

    if extension not in DOCUMENT_CONTENT_TYPES:
        raise ValidationError(
            'Upload a PDF, Word, OpenDocument, RTF, text, PNG, or JPEG file.'
        )

    if uploaded_file.size > MAX_DOCUMENT_FILE_SIZE:
        raise ValidationError('Document files must be 4 MB or smaller.')

    original_position = uploaded_file.tell() if hasattr(uploaded_file, 'tell') else 0

    try:
        uploaded_file.seek(0)
        header = uploaded_file.read(4096)

        if header.startswith((b'MZ', b'\x7fELF')):
            raise ValidationError('Executable files are not allowed.')

        valid_content = False

        if extension == '.pdf':
            valid_content = header.startswith(b'%PDF-')
        elif extension == '.png':
            valid_content = header.startswith(b'\x89PNG\r\n\x1a\n')
        elif extension in {'.jpg', '.jpeg'}:
            valid_content = header.startswith(b'\xff\xd8\xff')
        elif extension == '.doc':
            valid_content = header.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1')
        elif extension == '.rtf':
            valid_content = header.lstrip().startswith(b'{\\rtf')
        elif extension == '.txt':
            valid_content = b'\x00' not in header
        elif extension in {'.docx', '.odt'}:
            uploaded_file.seek(0)
            try:
                with ZipFile(uploaded_file) as archive:
                    names = set(archive.namelist())
                    if extension == '.docx':
                        valid_content = '[Content_Types].xml' in names and any(
                            name.startswith('word/') for name in names
                        )
                    else:
                        valid_content = 'mimetype' in names and (
                            archive.read('mimetype')
                            == b'application/vnd.oasis.opendocument.text'
                        )
            except (BadZipFile, KeyError):
                valid_content = False

        if not valid_content:
            raise ValidationError('The file contents do not match the selected file type.')
    finally:
        uploaded_file.seek(original_position)


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


class RequestThrottle(models.Model):
    scope = models.CharField(max_length=50)
    identifier_hash = models.CharField(max_length=64)
    window_started = models.DateTimeField()
    request_count = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['scope', 'identifier_hash'],
                name='request_throttle_scope_identifier_unique',
            ),
        ]
        indexes = [
            models.Index(fields=['window_started'], name='request_throttle_window_idx'),
        ]


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

    recruiter_name = models.CharField(
        max_length=150,
        blank=True
    )

    recruiter_email = models.EmailField(
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
        default='EUR',
        validators=[
            RegexValidator(
                regex=r'^[A-Za-z]{3}$',
                message='Enter a three-letter currency code, such as EUR or USD.',
            )
        ]
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
        blank=True,
        validators=[MaxLengthValidator(5000)],
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
        self.location = (self.location or '').strip()
        self.source = (self.source or '').strip()
        self.recruiter_name = (self.recruiter_name or '').strip()
        self.recruiter_email = (self.recruiter_email or '').strip().lower()
        self.currency = (self.currency or 'EUR').strip().upper()

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
        blank=True,
        validators=[MaxLengthValidator(5000)],
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
        ('certificate', 'Certificate'),
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
    file = models.FileField(
        upload_to=document_upload_path,
        validators=[validate_document_file],
        max_length=500,
        blank=True,
    )
    original_filename = models.CharField(max_length=255, blank=True)
    file_size = models.PositiveIntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True, validators=[MaxLengthValidator(5000)])
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
    notes = models.TextField(blank=True, validators=[MaxLengthValidator(5000)])
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
