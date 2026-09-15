from django import forms
from django.utils import timezone
from .models import JobApplication


class JobApplicationForm(forms.ModelForm):
    class Meta:
        model = JobApplication

        fields = [
            'company',
            'job_title',
            'location',
            'job_url',
            'employment_type',
            'status',
            'salary',
            'application_date',
            'notes',
        ]
        labels = {
            'job_url': 'Job URL (optional)',
        }
        widgets = {
            'job_url': forms.TextInput(),
            'application_date': forms.DateInput(attrs={'type': 'date'}),
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
