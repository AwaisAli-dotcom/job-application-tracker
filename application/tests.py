from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import JobApplication


class AuthenticationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='authuser',
            password='testpass123'
        )
        self.other_user = User.objects.create_user(
            username='privateuser',
            password='testpass123'
        )
        self.user_application = JobApplication.objects.create(
            user=self.user,
            company='Visible Company',
            job_title='Frontend Developer'
        )
        self.other_application = JobApplication.objects.create(
            user=self.other_user,
            company='Hidden Company',
            job_title='Backend Developer'
        )

    def test_login_works(self):
        response = self.client.post(
            reverse('login'),
            {
                'username': 'authuser',
                'password': 'testpass123',
            }
        )

        self.assertRedirects(response, reverse('application_list'))
        self.assertEqual(
            int(self.client.session['_auth_user_id']),
            self.user.pk
        )

    def test_invalid_login_is_rejected(self):
        response = self.client.post(
            reverse('login'),
            {
                'username': 'authuser',
                'password': 'wrong-password',
            }
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_registration_works_and_logs_user_in(self):
        response = self.client.post(
            reverse('register'),
            {
                'username': 'newuser',
                'password1': 'StrongPass12345!',
                'password2': 'StrongPass12345!',
            }
        )

        User = get_user_model()
        new_user = User.objects.get(username='newuser')
        self.assertRedirects(response, reverse('application_list'))
        self.assertTrue(new_user.check_password('StrongPass12345!'))
        self.assertEqual(
            int(self.client.session['_auth_user_id']),
            new_user.pk
        )

    def test_logout_works(self):
        self.client.login(username='authuser', password='testpass123')

        response = self.client.post(reverse('logout'))

        self.assertRedirects(response, reverse('login'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse('application_list'))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('application_list')}"
        )

    def test_authenticated_user_can_access_own_application_list(self):
        self.client.login(username='authuser', password='testpass123')

        response = self.client.get(reverse('application_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.user_application.company)

    def test_one_users_applications_are_hidden_from_another_user(self):
        self.client.login(username='authuser', password='testpass123')

        response = self.client.get(reverse('application_list'))

        self.assertContains(response, self.user_application.company)
        self.assertNotContains(response, self.other_application.company)


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
