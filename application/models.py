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

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='saved'
    )

    salary = models.CharField(
        max_length=100,
        blank=True
    )

    application_date = models.DateField(
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