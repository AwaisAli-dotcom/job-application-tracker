from django import forms
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
        widgets = {
    'application_date': forms.DateInput(attrs={'type': 'date'}),
}