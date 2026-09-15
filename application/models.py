from django.db import models
from django.conf import settings


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

    company = models.CharField(max_length=150)
    job_title = models.CharField(max_length=150)

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
        blank=True
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
