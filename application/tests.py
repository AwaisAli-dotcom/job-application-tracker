from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import JobApplication


class JobApplicationDeleteTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(
            username='owner',
            password='testpass123'
        )
        self.other_user = User.objects.create_user(
            username='other',
            password='testpass123'
        )
        self.application = JobApplication.objects.create(
            user=self.owner,
            company='Example Company',
            job_title='Python Developer',
            status='applied'
        )

    def test_owner_can_view_delete_confirmation(self):
        self.client.login(username='owner', password='testpass123')

        response = self.client.get(
            reverse('application_delete', args=[self.application.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Delete Job Application')
        self.assertTrue(
            JobApplication.objects.filter(pk=self.application.pk).exists()
        )

    def test_get_request_does_not_delete_application(self):
        self.client.login(username='owner', password='testpass123')

        self.client.get(reverse('application_delete', args=[self.application.pk]))

        self.assertTrue(
            JobApplication.objects.filter(pk=self.application.pk).exists()
        )

    def test_owner_can_delete_application_with_post(self):
        self.client.login(username='owner', password='testpass123')

        response = self.client.post(
            reverse('application_delete', args=[self.application.pk])
        )

        self.assertRedirects(response, reverse('application_list'))
        self.assertFalse(
            JobApplication.objects.filter(pk=self.application.pk).exists()
        )

    def test_user_cannot_delete_another_users_application(self):
        self.client.login(username='other', password='testpass123')

        response = self.client.post(
            reverse('application_delete', args=[self.application.pk])
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(
            JobApplication.objects.filter(pk=self.application.pk).exists()
        )

    def test_user_cannot_view_another_users_delete_confirmation(self):
        self.client.login(username='other', password='testpass123')

        response = self.client.get(
            reverse('application_delete', args=[self.application.pk])
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(
            JobApplication.objects.filter(pk=self.application.pk).exists()
        )
