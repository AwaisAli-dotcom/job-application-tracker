from django import forms
from django.utils import timezone
from .models import ApplicationDocument, Interview, JobApplication, Reminder


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
            'status',
            'salary',
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
            'salary': {
                'required': 'Salary is required.',
            },
            'application_date': {
                'required': 'Application date is required.',
            },
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['location'].required = True
        self.fields['salary'].required = True
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

    def clean_currency(self):
        currency = self.cleaned_data.get('currency', '').strip().upper()

        return currency or 'EUR'

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
            'outcome',
            'notes',
        ]
        widgets = {
            'scheduled_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }
        error_messages = {
            'scheduled_at': {
                'required': 'Interview date and time is required.',
            },
        }


class ApplicationDocumentForm(forms.ModelForm):
    class Meta:
        model = ApplicationDocument
        fields = [
            'title',
            'document_type',
            'link',
            'notes',
        ]
        labels = {
            'link': 'Document link (optional)',
        }
        widgets = {
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
            'due_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }
        error_messages = {
            'title': {
                'required': 'Reminder title is required.',
            },
            'due_at': {
                'required': 'Reminder date and time is required.',
            },
        }
