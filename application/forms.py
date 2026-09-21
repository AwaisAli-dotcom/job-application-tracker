from pathlib import Path
from urllib.parse import urlsplit

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.files.uploadedfile import UploadedFile
from django.utils.text import get_valid_filename
from django.utils import timezone

from .models import (
    ApplicationDocument,
    Interview,
    JobApplication,
    Reminder,
    document_content_type,
)


User = get_user_model()


def validate_http_url(value, message):
    if value and urlsplit(value).scheme.lower() not in {'http', 'https'}:
        raise forms.ValidationError(message)

    return value


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email')

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()

        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email already exists.')

        return email


class ProfileForm(forms.ModelForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ('username', 'email')

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()

        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('An account with this email already exists.')

        return email


class JobApplicationForm(forms.ModelForm):
    class Meta:
        model = JobApplication

        fields = [
            'company',
            'job_title',
            'location',
            'job_url',
            'employment_type',
            'work_mode',
            'source',
            'recruiter_name',
            'recruiter_email',
            'status',
            'salary_min',
            'salary_max',
            'currency',
            'application_date',
            'deadline',
            'notes',
        ]
        labels = {
            'job_url': 'Job URL (optional)',
            'salary_min': 'Salary minimum (optional)',
            'salary_max': 'Salary maximum (optional)',
            'currency': 'Currency (optional)',
            'deadline': 'Deadline (optional)',
            'recruiter_name': 'Recruiter or contact name (optional)',
            'recruiter_email': 'Recruiter email (optional)',
        }
        widgets = {
            'job_url': forms.TextInput(),
            'application_date': forms.DateInput(attrs={'type': 'date'}),
            'deadline': forms.DateInput(attrs={'type': 'date'}),
        }
        error_messages = {
            'company': {
                'required': 'Company name is required.',
            },
            'job_title': {
                'required': 'Job title is required.',
            },
            'location': {
                'required': 'Location is required.',
            },
            'job_url': {
                'invalid': 'Enter a valid job URL.',
            },
            'status': {
                'required': 'Status is required.',
            },
            'application_date': {
                'required': 'Application date is required.',
            },
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['location'].required = True
        self.fields['application_date'].required = True
        self.fields['currency'].required = False
        self.fields['currency'].initial = 'EUR'

    def clean_company(self):
        company = self.cleaned_data.get('company', '').strip()

        if not company:
            raise forms.ValidationError('Company name is required.')

        return company

    def clean_job_title(self):
        job_title = self.cleaned_data.get('job_title', '').strip()

        if not job_title:
            raise forms.ValidationError('Job title is required.')

        return job_title

    def clean_location(self):
        location = self.cleaned_data.get('location', '').strip()

        if not location:
            raise forms.ValidationError('Location is required.')

        return location

    def clean_application_date(self):
        application_date = self.cleaned_data.get('application_date')

        if application_date and application_date > timezone.localdate():
            raise forms.ValidationError('Application date cannot be in the future.')

        return application_date

    def clean_job_url(self):
        return validate_http_url(
            self.cleaned_data.get('job_url', ''),
            'Enter a valid job URL using http:// or https://.',
        )

    def clean_currency(self):
        currency = self.cleaned_data.get('currency', '').strip().upper()

        return currency or 'EUR'

    def clean_recruiter_name(self):
        return self.cleaned_data.get('recruiter_name', '').strip()

    def clean(self):
        cleaned_data = super().clean()
        salary_min = cleaned_data.get('salary_min')
        salary_max = cleaned_data.get('salary_max')
        application_date = cleaned_data.get('application_date')
        deadline = cleaned_data.get('deadline')

        if salary_min is not None and salary_min < 0:
            self.add_error('salary_min', 'Salary minimum cannot be negative.')

        if salary_max is not None and salary_max < 0:
            self.add_error('salary_max', 'Salary maximum cannot be negative.')

        valid_salary_min = salary_min is not None and salary_min >= 0
        valid_salary_max = salary_max is not None and salary_max >= 0

        if valid_salary_min and valid_salary_max and salary_max < salary_min:
            self.add_error('salary_max', 'Salary maximum must be greater than or equal to salary minimum.')

        if application_date and deadline and deadline < application_date:
            self.add_error('deadline', 'Deadline cannot be before the application date.')

        return cleaned_data


class InterviewForm(forms.ModelForm):
    class Meta:
        model = Interview
        fields = [
            'interview_type',
            'mode',
            'scheduled_at',
            'interviewer',
            'location_or_link',
            'outcome',
            'notes',
        ]
        labels = {
            'interviewer': 'Interviewer (optional)',
            'location_or_link': 'Location or meeting link (optional)',
        }
        widgets = {
            'scheduled_at': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={'type': 'datetime-local'},
            ),
        }
        error_messages = {
            'scheduled_at': {
                'required': 'Interview date and time is required.',
            },
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['scheduled_at'].input_formats = ['%Y-%m-%dT%H:%M']


class ApplicationDocumentForm(forms.ModelForm):
    class Meta:
        model = ApplicationDocument
        fields = [
            'title',
            'document_type',
            'file',
            'link',
            'notes',
        ]
        labels = {
            'file': 'File (optional)',
            'link': 'Document link (optional)',
        }
        help_texts = {
            'file': 'PDF, Word, OpenDocument, RTF, text, PNG, or JPEG; maximum 10 MB.',
        }
        widgets = {
            'file': forms.ClearableFileInput(
                attrs={'accept': '.pdf,.doc,.docx,.odt,.rtf,.txt,.png,.jpg,.jpeg'}
            ),
            'link': forms.TextInput(),
        }
        error_messages = {
            'title': {
                'required': 'Document title is required.',
            },
            'link': {
                'invalid': 'Enter a valid document link.',
            },
        }

    def clean_link(self):
        return validate_http_url(
            self.cleaned_data.get('link', ''),
            'Enter a valid document link using http:// or https://.',
        )

    def save(self, commit=True):
        document = super().save(commit=False)
        uploaded_file = self.cleaned_data.get('file')

        if isinstance(uploaded_file, UploadedFile):
            document.original_filename = get_valid_filename(
                Path(uploaded_file.name).name
            )[:255]
            document.file_size = uploaded_file.size
            document.content_type = document_content_type(uploaded_file.name)
        elif not uploaded_file:
            document.original_filename = ''
            document.file_size = None
            document.content_type = ''

        if commit:
            document.save()

        return document


class ReminderForm(forms.ModelForm):
    class Meta:
        model = Reminder
        fields = [
            'title',
            'due_at',
            'completed',
            'notes',
        ]
        widgets = {
            'due_at': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={'type': 'datetime-local'},
            ),
        }
        error_messages = {
            'title': {
                'required': 'Reminder title is required.',
            },
            'due_at': {
                'required': 'Reminder date and time is required.',
            },
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['due_at'].input_formats = ['%Y-%m-%dT%H:%M']
