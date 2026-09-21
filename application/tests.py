import re
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone as django_timezone

from .forms import JobApplicationForm
from .models import (
    MAX_DOCUMENT_FILE_SIZE,
    ApplicationDocument,
    Interview,
    JobApplication,
    Reminder,
    RequestThrottle,
    StatusHistory,
)
from .throttling import consume_request_limit, get_client_ip


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

        self.assertRedirects(response, reverse('dashboard'))
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

    def test_login_form_preserves_requested_destination(self):
        response = self.client.get(
            reverse('login'),
            {'next': reverse('application_list')},
        )

        self.assertContains(
            response,
            f'<input type="hidden" name="next" value="{reverse("application_list")}">',
        )

    def test_registration_works_and_logs_user_in(self):
        response = self.client.post(
            reverse('register'),
            {
                'username': 'newuser',
                'email': 'NewUser@Example.com',
                'password1': 'StrongPass12345!',
                'password2': 'StrongPass12345!',
            }
        )

        User = get_user_model()
        new_user = User.objects.get(username='newuser')
        self.assertRedirects(response, reverse('dashboard'))
        self.assertTrue(new_user.check_password('StrongPass12345!'))
        self.assertEqual(new_user.email, 'newuser@example.com')
        self.assertEqual(
            int(self.client.session['_auth_user_id']),
            new_user.pk
        )

    def test_registration_rejects_duplicate_email(self):
        self.user.email = 'used@example.com'
        self.user.save(update_fields=['email'])

        response = self.client.post(
            reverse('register'),
            {
                'username': 'anotheruser',
                'email': 'USED@example.com',
                'password1': 'StrongPass12345!',
                'password2': 'StrongPass12345!',
            }
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'An account with this email already exists.')
        self.assertFalse(get_user_model().objects.filter(username='anotheruser').exists())

    def test_profile_requires_login(self):
        response = self.client.get(reverse('profile'))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('profile')}"
        )

    def test_user_can_update_profile(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('profile'),
            {
                'username': 'updatedauthuser',
                'email': 'UPDATED@example.com',
            },
            follow=True,
        )

        self.user.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.user.username, 'updatedauthuser')
        self.assertEqual(self.user.email, 'updated@example.com')
        self.assertContains(response, 'Your account details have been updated.')

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

    def test_csrf_failure_uses_friendly_page(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        response = csrf_client.post(reverse('application_create'), {})

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, 'Access not allowed', status_code=403)


class PasswordManagementTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='passworduser',
            email='password@example.com',
            password='CurrentPass123!',
        )

    def test_login_page_links_to_password_reset(self):
        response = self.client.get(reverse('login'))

        self.assertContains(response, reverse('password_reset'))
        self.assertContains(response, 'Forgot password?')

    def test_account_page_links_to_password_change(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('profile'))

        self.assertContains(response, reverse('password_change'))
        self.assertContains(response, 'Change Password')

    def test_password_change_requires_login(self):
        response = self.client.get(reverse('password_change'))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('password_change')}",
        )

    def test_user_can_change_password_and_remain_logged_in(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('password_change'),
            {
                'old_password': 'CurrentPass123!',
                'new_password1': 'NewSecurePass456!',
                'new_password2': 'NewSecurePass456!',
            },
        )

        self.assertRedirects(response, reverse('password_change_done'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewSecurePass456!'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_wrong_current_password_is_rejected(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('password_change'),
            {
                'old_password': 'WrongPassword123!',
                'new_password1': 'NewSecurePass456!',
                'new_password2': 'NewSecurePass456!',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Your old password was entered incorrectly.')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('CurrentPass123!'))

    def test_password_reset_sends_secure_token_email(self):
        response = self.client.post(
            reverse('password_reset'),
            {'email': self.user.email},
        )

        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertIn('Reset your Job Application Tracker password', mail.outbox[0].subject)
        self.assertRegex(
            mail.outbox[0].body,
            r'http://testserver/accounts/reset/[^/]+/[^/]+/',
        )

    def test_unknown_reset_email_uses_same_success_page(self):
        response = self.client.post(
            reverse('password_reset'),
            {'email': 'unknown@example.com'},
        )

        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_token_can_replace_password(self):
        self.client.post(
            reverse('password_reset'),
            {'email': self.user.email},
        )
        reset_path = re.search(
            r'http://testserver(?P<path>/accounts/reset/[^/]+/[^/]+/)',
            mail.outbox[0].body,
        ).group('path')

        response = self.client.get(reset_path)
        self.assertRedirects(response, response.url)

        response = self.client.post(
            response.url,
            {
                'new_password1': 'ResetSecurePass789!',
                'new_password2': 'ResetSecurePass789!',
            },
        )

        self.assertRedirects(response, reverse('password_reset_complete'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('ResetSecurePass789!'))

    def test_invalid_password_reset_token_is_rejected(self):
        response = self.client.get(
            reverse(
                'password_reset_confirm',
                kwargs={'uidb64': 'invalid', 'token': 'invalid-token'},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This reset link is invalid or has expired.')
        self.assertNotContains(response, 'Set New Password')


class AuthenticationRateLimitTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='ratelimituser',
            email='ratelimit@example.com',
            password='RateLimitPass123!',
        )

    @override_settings(AXES_ENABLED=True)
    def test_failed_logins_are_temporarily_limited(self):
        from axes.models import AccessAttempt

        for _ in range(settings.AXES_FAILURE_LIMIT):
            response = self.client.post(
                reverse('login'),
                {
                    'username': self.user.username,
                    'password': 'wrong-password',
                },
            )

        self.assertEqual(response.status_code, 429)
        self.assertContains(response, 'Too many attempts', status_code=429)
        self.assertNotIn('wrong-password', AccessAttempt.objects.first().post_data)

        response = self.client.post(
            reverse('login'),
            {
                'username': self.user.username,
                'password': 'RateLimitPass123!',
            },
        )

        self.assertEqual(response.status_code, 429)

    def test_registration_is_limited_after_five_posts(self):
        for _ in range(5):
            response = self.client.post(reverse('register'), {})
            self.assertEqual(response.status_code, 200)

        response = self.client.post(reverse('register'), {})

        self.assertEqual(response.status_code, 429)
        self.assertContains(response, 'Too many attempts', status_code=429)
        self.assertIn('Retry-After', response)

    def test_password_reset_request_is_limited_by_email(self):
        for _ in range(5):
            response = self.client.post(
                reverse('password_reset'),
                {'email': self.user.email},
            )
            self.assertRedirects(response, reverse('password_reset_done'))

        response = self.client.post(
            reverse('password_reset'),
            {'email': self.user.email},
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(len(mail.outbox), 5)

    def test_rate_limit_identifiers_are_hashed(self):
        consume_request_limit('privacy_test', self.user.email, 5, 3600)

        throttle = RequestThrottle.objects.get(scope='privacy_test')
        self.assertNotEqual(throttle.identifier_hash, self.user.email)
        self.assertEqual(len(throttle.identifier_hash), 64)

    def test_expired_rate_limit_window_starts_again(self):
        consume_request_limit('window_test', '127.0.0.1', 1, 60)
        throttle = RequestThrottle.objects.get(scope='window_test')
        throttle.window_started = django_timezone.now() - timedelta(minutes=2)
        throttle.save(update_fields=['window_started'])

        retry_after = consume_request_limit('window_test', '127.0.0.1', 1, 60)

        self.assertIsNone(retry_after)
        throttle.refresh_from_db()
        self.assertEqual(throttle.request_count, 1)

    @override_settings(TRUST_VERCEL_PROXY=True)
    def test_vercel_client_ip_uses_trusted_platform_header(self):
        response = self.client.get(
            reverse('home'),
            HTTP_X_VERCEL_FORWARDED_FOR='203.0.113.8',
            REMOTE_ADDR='127.0.0.1',
        )

        self.assertEqual(get_client_ip(response.wsgi_request), '203.0.113.8')

    @override_settings(TRUST_VERCEL_PROXY=False)
    def test_untrusted_forwarded_header_is_ignored_locally(self):
        response = self.client.get(
            reverse('home'),
            HTTP_X_VERCEL_FORWARDED_FOR='203.0.113.8',
            REMOTE_ADDR='127.0.0.1',
        )

        self.assertEqual(get_client_ip(response.wsgi_request), '127.0.0.1')


class DashboardTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='dashboarduser',
            password='testpass123'
        )
        self.other_user = User.objects.create_user(
            username='otherdashboarduser',
            password='testpass123'
        )
        today = django_timezone.localdate()
        JobApplication.objects.create(
            user=self.user,
            company='Saved Company',
            job_title='Saved Role',
            status='saved',
            deadline=today + timedelta(days=5),
        )
        JobApplication.objects.create(
            user=self.user,
            company='Interview Company',
            job_title='Interview Role',
            status='interview',
            application_date=today
        )
        JobApplication.objects.create(
            user=self.user,
            company='Offer Company',
            job_title='Offer Role',
            status='offer',
            application_date=today
        )
        JobApplication.objects.create(
            user=self.other_user,
            company='Hidden Dashboard Company',
            job_title='Hidden Role',
            status='offer',
            application_date=today,
            deadline=today + timedelta(days=4),
        )

    def test_home_page_is_public(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Job Application Tracker')
        self.assertContains(response, 'width=device-width, initial-scale=1')

    def test_about_and_privacy_pages_are_public(self):
        about_response = self.client.get(reverse('about'))
        privacy_response = self.client.get(reverse('privacy'))

        self.assertEqual(about_response.status_code, 200)
        self.assertEqual(privacy_response.status_code, 200)
        self.assertContains(about_response, 'private workspace')
        self.assertContains(privacy_response, 'visible only after signing in')

    @override_settings(DEBUG=False)
    def test_unknown_page_uses_friendly_404_template(self):
        response = self.client.get('/this-page-does-not-exist/')

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Page not found', status_code=404)

    def test_authenticated_home_redirects_to_dashboard(self):
        self.client.login(username='dashboarduser', password='testpass123')

        response = self.client.get(reverse('home'))

        self.assertRedirects(response, reverse('dashboard'))

    def test_anonymous_dashboard_redirects_to_login(self):
        response = self.client.get(reverse('dashboard'))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('dashboard')}"
        )

    def test_dashboard_counts_current_users_applications(self):
        self.client.login(username='dashboarduser', password='testpass123')

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_applications'], 3)
        self.assertEqual(response.context['submitted_count'], 2)
        self.assertEqual(response.context['applied_this_month'], 2)
        self.assertEqual(response.context['interviews_count'], 1)
        self.assertEqual(response.context['offers_count'], 1)
        self.assertEqual(response.context['interview_rate'], 50)
        self.assertEqual(response.context['offer_rate'], 50)
        self.assertEqual(response.context['response_rate'], 100)
        self.assertContains(response, 'Interview Company')
        self.assertContains(response, 'Upcoming Deadlines')
        self.assertContains(response, 'Saved Company')
        self.assertNotContains(response, 'Hidden Dashboard Company')

    def test_interview_rate_counts_interview_records(self):
        applied_application = JobApplication.objects.create(
            user=self.user,
            company='Recorded Interview Company',
            job_title='Engineer',
            status='applied',
            application_date=django_timezone.localdate(),
        )
        Interview.objects.create(
            user=self.user,
            application=applied_application,
            scheduled_at=django_timezone.now() + timedelta(days=1),
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.context['submitted_count'], 3)
        self.assertEqual(response.context['interview_rate'], 67)

    def test_empty_dashboard_has_helpful_empty_state(self):
        empty_user = get_user_model().objects.create_user(
            username='emptydashboarduser',
            password='testpass123'
        )
        self.client.force_login(empty_user)

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No applications yet')


class ApplicationExportTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='exportuser',
            password='testpass123'
        )
        self.other_user = User.objects.create_user(
            username='otherexportuser',
            password='testpass123'
        )
        self.application = JobApplication.objects.create(
            user=self.user,
            company='Export Company',
            job_title='Data Developer',
            location='Vilnius',
            status='applied',
            notes='=HYPERLINK("https://example.com")',
        )
        JobApplication.objects.create(
            user=self.other_user,
            company='Private Export Company',
            job_title='Hidden Role',
        )

    def test_anonymous_export_redirects_to_login(self):
        response = self.client.get(reverse('application_export'))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('application_export')}"
        )

    def test_export_contains_only_current_users_applications(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('application_export'))
        content = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('attachment; filename="job-applications.csv"', response['Content-Disposition'])
        self.assertIn('Export Company', content)
        self.assertNotIn('Private Export Company', content)

    def test_export_neutralizes_spreadsheet_formulas(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('application_export'))

        self.assertIn("'=HYPERLINK", response.content.decode('utf-8'))


class ModelValidationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='modeluser', password='testpass123')
        self.other_user = User.objects.create_user(username='othermodeluser', password='testpass123')
        self.application = JobApplication.objects.create(
            user=self.user,
            company='Model Company',
            job_title='Engineer',
            application_date=django_timezone.localdate(),
        )

    def test_application_defaults_and_string_representation(self):
        self.assertEqual(self.application.status, 'saved')
        self.assertEqual(str(self.application), 'Model Company - Engineer')

    def test_model_rejects_invalid_salary_range(self):
        self.application.salary_min = 4000
        self.application.salary_max = 3000

        with self.assertRaises(ValidationError):
            self.application.full_clean()

    def test_model_rejects_one_character_company_and_job_title(self):
        self.application.company = 'A'
        self.application.job_title = 'B'

        with self.assertRaises(ValidationError) as error:
            self.application.full_clean()

        self.assertIn('company', error.exception.message_dict)
        self.assertIn('job_title', error.exception.message_dict)

    def test_model_rejects_whitespace_only_names(self):
        self.application.company = '   '
        self.application.job_title = '   '

        with self.assertRaises(ValidationError) as error:
            self.application.full_clean()

        self.assertIn('company', error.exception.message_dict)
        self.assertIn('job_title', error.exception.message_dict)

    def test_model_rejects_non_http_job_url(self):
        self.application.job_url = 'ftp://example.com/job'

        with self.assertRaises(ValidationError) as error:
            self.application.full_clean()

        self.assertIn('job_url', error.exception.message_dict)

    def test_model_requires_application_date(self):
        self.application.application_date = None

        with self.assertRaises(ValidationError) as error:
            self.application.full_clean()

        self.assertIn('application_date', error.exception.message_dict)

    def test_model_rejects_future_application_date(self):
        self.application.application_date = django_timezone.localdate() + timedelta(days=1)

        with self.assertRaises(ValidationError) as error:
            self.application.full_clean()

        self.assertIn('application_date', error.exception.message_dict)

    def test_database_rejects_negative_salary(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            JobApplication.objects.create(
                user=self.user,
                company='Invalid Salary Company',
                job_title='Engineer',
                salary_min=-1,
            )

    def test_related_object_owner_must_match_application_owner(self):
        interview = Interview(
            user=self.other_user,
            application=self.application,
            scheduled_at=django_timezone.now(),
        )

        with self.assertRaises(ValidationError):
            interview.full_clean()

    def test_status_history_rejects_unchanged_status(self):
        history = StatusHistory(
            user=self.user,
            application=self.application,
            old_status='saved',
            new_status='saved',
        )

        with self.assertRaises(ValidationError):
            history.full_clean()


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


class JobApplicationDetailTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(
            username='detailowner',
            password='testpass123'
        )
        self.other_user = User.objects.create_user(
            username='detailother',
            password='testpass123'
        )
        self.application = JobApplication.objects.create(
            user=self.owner,
            company='Detail Company',
            job_title='Django Developer',
            location='Remote',
            job_url='https://example.com/job',
            employment_type='full_time',
            work_mode='remote',
            source='LinkedIn',
            recruiter_name='Morgan Recruiter',
            recruiter_email='morgan@example.com',
            status='interview',
            salary='50000',
            salary_min='45000',
            salary_max='55000',
            currency='EUR',
            application_date='2026-09-01',
            deadline='2026-09-15',
            notes='Prepare for technical interview.'
        )

    def test_owner_can_view_application_detail(self):
        self.client.login(username='detailowner', password='testpass123')

        response = self.client.get(
            reverse('application_detail', args=[self.application.pk])
        )

        self.assertEqual(response.status_code, 200)

    def test_another_user_cannot_view_application_detail(self):
        self.client.login(username='detailother', password='testpass123')

        response = self.client.get(
            reverse('application_detail', args=[self.application.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_anonymous_user_is_redirected_to_login_for_detail(self):
        detail_url = reverse('application_detail', args=[self.application.pk])

        response = self.client.get(detail_url)

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={detail_url}"
        )

    def test_application_data_appears_on_detail_page(self):
        self.client.login(username='detailowner', password='testpass123')

        response = self.client.get(
            reverse('application_detail', args=[self.application.pk])
        )

        self.assertContains(response, 'Detail Company')
        self.assertContains(response, 'Django Developer')
        self.assertContains(response, 'Remote')
        self.assertContains(response, 'https://example.com/job')
        self.assertContains(response, 'Full-time')
        self.assertContains(response, 'Remote')
        self.assertContains(response, 'LinkedIn')
        self.assertContains(response, 'Morgan Recruiter')
        self.assertContains(response, 'morgan@example.com')
        self.assertContains(response, 'Interview')
        self.assertContains(response, '45000.00')
        self.assertContains(response, '55000.00')
        self.assertContains(response, 'EUR')
        self.assertContains(response, 'Sept. 15, 2026')
        self.assertContains(response, 'Prepare for technical interview.')

    def test_edit_page_uses_edit_heading(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse('application_update', args=[self.application.pk]))

        self.assertContains(response, 'Edit Job Application')
        self.assertContains(response, 'Save Changes')

    def test_legacy_salary_remains_visible_without_structured_values(self):
        self.application.salary_min = None
        self.application.salary_max = None
        self.application.save(update_fields=['salary_min', 'salary_max'])
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse('application_detail', args=[self.application.pk])
        )

        self.assertContains(response, 'Salary:')
        self.assertContains(response, '50000')

    def test_status_history_appears_on_detail_page(self):
        StatusHistory.objects.create(
            user=self.owner,
            application=self.application,
            old_status='applied',
            new_status='interview'
        )
        self.client.login(username='detailowner', password='testpass123')

        response = self.client.get(
            reverse('application_detail', args=[self.application.pk])
        )

        self.assertContains(response, 'Status History')
        self.assertContains(response, 'Applied')
        self.assertContains(response, 'Interview')

    def test_nonexistent_application_detail_returns_404(self):
        self.client.login(username='detailowner', password='testpass123')

        response = self.client.get(reverse('application_detail', args=[99999]))

        self.assertEqual(response.status_code, 404)


class JobApplicationKanbanTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='kanbanuser',
            password='testpass123'
        )
        self.other_user = User.objects.create_user(
            username='otherkanbanuser',
            password='testpass123'
        )
        self.application = JobApplication.objects.create(
            user=self.user,
            company='Kanban Company',
            job_title='Python Developer',
            location='Remote',
            status='applied',
            application_date=django_timezone.localdate(),
        )
        self.hidden_application = JobApplication.objects.create(
            user=self.other_user,
            company='Hidden Kanban Company',
            job_title='Secret Developer',
            location='Remote',
            status='interview',
            application_date=django_timezone.localdate(),
        )

    def test_owner_can_view_kanban_board(self):
        self.client.login(username='kanbanuser', password='testpass123')

        response = self.client.get(reverse('kanban_board'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Kanban Company')
        self.assertContains(response, 'Applied')

    def test_kanban_board_never_exposes_other_users_applications(self):
        self.client.login(username='kanbanuser', password='testpass123')

        response = self.client.get(reverse('kanban_board'))

        self.assertContains(response, self.application.company)
        self.assertNotContains(response, self.hidden_application.company)

    def test_anonymous_user_is_redirected_from_kanban(self):
        response = self.client.get(reverse('kanban_board'))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('kanban_board')}"
        )

    def test_owner_can_update_status(self):
        self.client.login(username='kanbanuser', password='testpass123')

        response = self.client.post(
            reverse('application_status_update', args=[self.application.pk]),
            {'status': 'interview'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {'ok': True, 'status': 'interview', 'status_label': 'Interview'}
        )
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'interview')
        self.assertTrue(
            StatusHistory.objects.filter(
                user=self.user,
                application=self.application,
                old_status='applied',
                new_status='interview'
            ).exists()
        )

    def test_status_update_fallback_redirects_to_kanban(self):
        self.client.login(username='kanbanuser', password='testpass123')

        response = self.client.post(
            reverse('application_status_update', args=[self.application.pk]),
            {'status': 'technical_test'}
        )

        self.assertRedirects(response, reverse('kanban_board'))
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'technical_test')
        self.assertTrue(
            StatusHistory.objects.filter(
                user=self.user,
                application=self.application,
                old_status='applied',
                new_status='technical_test'
            ).exists()
        )

    def test_same_status_update_does_not_create_history(self):
        self.client.login(username='kanbanuser', password='testpass123')

        response = self.client.post(
            reverse('application_status_update', args=[self.application.pk]),
            {'status': 'applied'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            StatusHistory.objects.filter(application=self.application).exists()
        )

    def test_invalid_status_is_rejected(self):
        self.client.login(username='kanbanuser', password='testpass123')

        response = self.client.post(
            reverse('application_status_update', args=[self.application.pk]),
            {'status': 'not-real'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )

        self.assertEqual(response.status_code, 400)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'applied')

    def test_submitted_status_requires_application_date(self):
        saved_application = JobApplication.objects.create(
            user=self.user,
            company='Saved Company',
            job_title='Saved Role',
            status='saved',
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('application_status_update', args=[saved_application.pk]),
            {'status': 'applied'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(
            response.content,
            {'ok': False, 'error': 'Application date is required.'},
        )
        saved_application.refresh_from_db()
        self.assertEqual(saved_application.status, 'saved')
        self.assertFalse(StatusHistory.objects.filter(application=saved_application).exists())

    def test_get_status_update_is_rejected(self):
        self.client.login(username='kanbanuser', password='testpass123')

        response = self.client.get(
            reverse('application_status_update', args=[self.application.pk])
        )

        self.assertEqual(response.status_code, 405)

    def test_user_cannot_update_another_users_status(self):
        self.client.login(username='kanbanuser', password='testpass123')

        response = self.client.post(
            reverse('application_status_update', args=[self.hidden_application.pk]),
            {'status': 'offer'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )

        self.assertEqual(response.status_code, 404)
        self.hidden_application.refresh_from_db()
        self.assertEqual(self.hidden_application.status, 'interview')


class InterviewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='interviewuser',
            password='testpass123'
        )
        self.other_user = User.objects.create_user(
            username='otherinterviewuser',
            password='testpass123'
        )
        self.application = JobApplication.objects.create(
            user=self.user,
            company='Interview App Company',
            job_title='Django Developer',
            status='interview'
        )
        self.other_application = JobApplication.objects.create(
            user=self.other_user,
            company='Hidden Interview App Company',
            job_title='Secret Developer',
            status='interview'
        )
        self.future_time = django_timezone.now() + timedelta(days=2)
        self.past_time = django_timezone.now() - timedelta(days=2)
        self.interview = Interview.objects.create(
            user=self.user,
            application=self.application,
            interview_type='technical',
            mode='video',
            scheduled_at=self.future_time,
            notes='Prepare Django examples.'
        )
        self.hidden_interview = Interview.objects.create(
            user=self.other_user,
            application=self.other_application,
            interview_type='final',
            mode='phone',
            scheduled_at=self.future_time
        )

    def interview_form_data(self, **overrides):
        data = {
            'interview_type': 'hr_screen',
            'mode': 'video',
            'scheduled_at': (django_timezone.now() + timedelta(days=5)).strftime('%Y-%m-%dT%H:%M'),
            'interviewer': 'Sam Recruiter',
            'location_or_link': 'https://meet.example.com/interview',
            'outcome': '',
            'notes': 'Initial conversation.',
        }
        data.update(overrides)
        return data

    def test_interview_list_shows_only_current_users_interviews(self):
        self.client.login(username='interviewuser', password='testpass123')

        response = self.client.get(reverse('interview_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.application.company)
        self.assertNotContains(response, self.other_application.company)

    def test_anonymous_user_is_redirected_from_interviews(self):
        response = self.client.get(reverse('interview_list'))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('interview_list')}"
        )

    def test_owner_can_create_interview_for_own_application(self):
        self.client.login(username='interviewuser', password='testpass123')

        response = self.client.post(
            reverse('interview_create', args=[self.application.pk]),
            self.interview_form_data()
        )

        self.assertRedirects(
            response,
            reverse('application_detail', args=[self.application.pk])
        )
        self.assertTrue(
            Interview.objects.filter(
                user=self.user,
                application=self.application,
                interview_type='hr_screen',
                interviewer='Sam Recruiter',
                location_or_link='https://meet.example.com/interview',
            ).exists()
        )

    def test_user_cannot_create_interview_for_another_users_application(self):
        self.client.login(username='interviewuser', password='testpass123')

        response = self.client.post(
            reverse('interview_create', args=[self.other_application.pk]),
            self.interview_form_data()
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            Interview.objects.filter(
                user=self.user,
                application=self.other_application
            ).exists()
        )

    def test_owner_can_update_interview(self):
        self.client.login(username='interviewuser', password='testpass123')

        response = self.client.post(
            reverse('interview_update', args=[self.interview.pk]),
            self.interview_form_data(outcome='Moved to next round')
        )

        self.assertRedirects(
            response,
            reverse('application_detail', args=[self.application.pk])
        )
        self.interview.refresh_from_db()
        self.assertEqual(self.interview.outcome, 'Moved to next round')

    def test_edit_form_formats_existing_datetime_for_browser_input(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('interview_update', args=[self.interview.pk]))
        expected_value = django_timezone.localtime(self.interview.scheduled_at).strftime('%Y-%m-%dT%H:%M')

        self.assertContains(response, f'value="{expected_value}"')

    def test_user_cannot_update_another_users_interview(self):
        self.client.login(username='interviewuser', password='testpass123')

        response = self.client.post(
            reverse('interview_update', args=[self.hidden_interview.pk]),
            self.interview_form_data(outcome='Changed')
        )

        self.assertEqual(response.status_code, 404)
        self.hidden_interview.refresh_from_db()
        self.assertEqual(self.hidden_interview.outcome, '')

    def test_owner_can_delete_interview(self):
        self.client.login(username='interviewuser', password='testpass123')

        response = self.client.post(reverse('interview_delete', args=[self.interview.pk]))

        self.assertRedirects(
            response,
            reverse('application_detail', args=[self.application.pk])
        )
        self.assertFalse(Interview.objects.filter(pk=self.interview.pk).exists())

    def test_user_cannot_delete_another_users_interview(self):
        self.client.login(username='interviewuser', password='testpass123')

        response = self.client.post(reverse('interview_delete', args=[self.hidden_interview.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Interview.objects.filter(pk=self.hidden_interview.pk).exists())

    def test_interview_appears_on_application_detail(self):
        self.client.login(username='interviewuser', password='testpass123')

        response = self.client.get(reverse('application_detail', args=[self.application.pk]))

        self.assertContains(response, 'Technical')
        self.assertContains(response, 'Prepare Django examples.')

    def test_inconsistent_related_owner_is_not_exposed(self):
        Interview.objects.create(
            user=self.other_user,
            application=self.application,
            scheduled_at=self.future_time,
            notes='Private mismatched interview',
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('application_detail', args=[self.application.pk]))

        self.assertNotContains(response, 'Private mismatched interview')

    def test_dashboard_shows_upcoming_interviews(self):
        self.client.login(username='interviewuser', password='testpass123')

        response = self.client.get(reverse('dashboard'))

        self.assertContains(response, 'Upcoming Interviews')
        self.assertContains(response, self.application.company)
        self.assertNotContains(response, self.other_application.company)

    def test_past_interviews_are_separated_from_upcoming(self):
        Interview.objects.create(
            user=self.user,
            application=self.application,
            interview_type='final',
            mode='video',
            scheduled_at=self.past_time
        )
        self.client.login(username='interviewuser', password='testpass123')

        response = self.client.get(reverse('interview_list'))

        self.assertContains(response, 'Upcoming')
        self.assertContains(response, 'Past')


class DocumentReminderTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='metadatauser',
            password='testpass123'
        )
        self.other_user = User.objects.create_user(
            username='othermetadatauser',
            password='testpass123'
        )
        self.application = JobApplication.objects.create(
            user=self.user,
            company='Metadata Company',
            job_title='Python Developer',
            status='applied'
        )
        self.other_application = JobApplication.objects.create(
            user=self.other_user,
            company='Hidden Metadata Company',
            job_title='Secret Developer',
            status='applied'
        )
        self.document = ApplicationDocument.objects.create(
            user=self.user,
            application=self.application,
            title='CV Backend v2',
            document_type='cv',
            link='https://example.com/cv'
        )
        self.hidden_document = ApplicationDocument.objects.create(
            user=self.other_user,
            application=self.other_application,
            title='Hidden CV',
            document_type='cv'
        )
        self.reminder = Reminder.objects.create(
            user=self.user,
            application=self.application,
            title='Follow up',
            due_at=django_timezone.now() + timedelta(days=3)
        )
        self.hidden_reminder = Reminder.objects.create(
            user=self.other_user,
            application=self.other_application,
            title='Hidden reminder',
            due_at=django_timezone.now() + timedelta(days=3)
        )

    def document_form_data(self, **overrides):
        data = {
            'title': 'Cover Letter v1',
            'document_type': 'cover_letter',
            'link': 'https://example.com/cover-letter',
            'notes': 'Tailored for the company.',
        }
        data.update(overrides)
        return data

    def reminder_form_data(self, **overrides):
        data = {
            'title': 'Send follow-up email',
            'due_at': (django_timezone.now() + timedelta(days=5)).strftime('%Y-%m-%dT%H:%M'),
            'completed': '',
            'notes': 'Mention the technical interview.',
        }
        data.update(overrides)
        return data

    def pdf_upload(self, name='candidate-cv.pdf', content=b'%PDF-1.4\n%%EOF'):
        return SimpleUploadedFile(name, content, content_type='application/pdf')

    def test_owner_can_create_document_metadata(self):
        self.client.login(username='metadatauser', password='testpass123')

        response = self.client.post(
            reverse('document_create', args=[self.application.pk]),
            self.document_form_data()
        )

        self.assertRedirects(
            response,
            reverse('application_detail', args=[self.application.pk])
        )
        self.assertTrue(
            ApplicationDocument.objects.filter(
                user=self.user,
                application=self.application,
                title='Cover Letter v1'
            ).exists()
        )

    def test_owner_can_upload_private_document(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('document_create', args=[self.application.pk]),
            self.document_form_data(
                title='Uploaded CV',
                link='',
                file=self.pdf_upload('Awais CV 2026.pdf'),
            ),
        )

        self.assertRedirects(
            response,
            reverse('application_detail', args=[self.application.pk]),
        )
        document = ApplicationDocument.objects.get(title='Uploaded CV')
        self.assertEqual(document.original_filename, 'Awais_CV_2026.pdf')
        self.assertEqual(document.file_size, len(b'%PDF-1.4\n%%EOF'))
        self.assertEqual(document.content_type, 'application/pdf')
        self.assertNotIn('Awais_CV_2026', document.file.name)
        self.assertTrue(document.file.name.startswith(
            f'documents/user_{self.user.pk}/application_{self.application.pk}/'
        ))

    def test_document_upload_rejects_unsupported_file_type(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('document_create', args=[self.application.pk]),
            self.document_form_data(
                file=SimpleUploadedFile(
                    'program.exe',
                    b'MZ executable content',
                    content_type='application/octet-stream',
                ),
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'Upload a PDF, Word, OpenDocument, RTF, text, PNG, or JPEG file.',
        )

    def test_document_upload_rejects_disguised_executable(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('document_create', args=[self.application.pk]),
            self.document_form_data(
                file=self.pdf_upload('malware.pdf', b'MZ executable content'),
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Executable files are not allowed.')

    def test_document_upload_rejects_file_over_size_limit(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('document_create', args=[self.application.pk]),
            self.document_form_data(
                file=self.pdf_upload(
                    content=b'%PDF-' + b'0' * MAX_DOCUMENT_FILE_SIZE,
                ),
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Document files must be 4 MB or smaller.')

    @override_settings(R2_STORAGE_ENABLED=True)
    def test_production_download_redirects_to_short_lived_storage_url(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse('document_create', args=[self.application.pk]),
            self.document_form_data(title='R2 CV', file=self.pdf_upload()),
        )
        document = ApplicationDocument.objects.get(title='R2 CV')
        signed_url = 'https://storage.example.invalid/private-file?signature=temporary'

        with (
            patch.object(document.file.storage, 'exists', return_value=True),
            patch.object(document.file.storage, 'url', return_value=signed_url),
        ):
            response = self.client.get(reverse('document_download', args=[document.pk]))

        self.assertRedirects(response, signed_url, fetch_redirect_response=False)
        self.assertEqual(response['Cache-Control'], 'private, no-store')

    def test_owner_can_download_uploaded_document(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse('document_create', args=[self.application.pk]),
            self.document_form_data(
                title='Downloadable CV',
                file=self.pdf_upload(),
            ),
        )
        document = ApplicationDocument.objects.get(title='Downloadable CV')

        response = self.client.get(reverse('document_download', args=[document.pk]))
        content = b''.join(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(content, b'%PDF-1.4\n%%EOF')
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertIn('candidate-cv.pdf', response['Content-Disposition'])

    def test_anonymous_user_is_redirected_from_document_download(self):
        response = self.client.get(reverse('document_download', args=[self.document.pk]))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('document_download', args=[self.document.pk])}",
        )

    def test_user_cannot_download_another_users_document(self):
        self.hidden_document.file = self.pdf_upload('hidden.pdf')
        self.hidden_document.original_filename = 'hidden.pdf'
        self.hidden_document.file_size = len(b'%PDF-1.4\n%%EOF')
        self.hidden_document.content_type = 'application/pdf'
        self.hidden_document.save()
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('document_download', args=[self.hidden_document.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_document_without_file_cannot_be_downloaded(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('document_download', args=[self.document.pk]))

        self.assertEqual(response.status_code, 404)

    def test_replacing_document_removes_old_stored_file(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse('document_create', args=[self.application.pk]),
            self.document_form_data(title='Replaceable CV', file=self.pdf_upload('old.pdf')),
        )
        document = ApplicationDocument.objects.get(title='Replaceable CV')
        old_name = document.file.name
        storage = document.file.storage

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse('document_update', args=[document.pk]),
                self.document_form_data(
                    title='Replaceable CV',
                    file=self.pdf_upload('new.pdf', b'%PDF-1.5\n%%EOF'),
                ),
            )

        self.assertRedirects(
            response,
            reverse('application_detail', args=[self.application.pk]),
        )
        document.refresh_from_db()
        self.assertFalse(storage.exists(old_name))
        self.assertTrue(storage.exists(document.file.name))

    def test_deleting_document_removes_stored_file(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse('document_create', args=[self.application.pk]),
            self.document_form_data(title='Temporary CV', file=self.pdf_upload()),
        )
        document = ApplicationDocument.objects.get(title='Temporary CV')
        name = document.file.name
        storage = document.file.storage

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('document_delete', args=[document.pk]))

        self.assertRedirects(
            response,
            reverse('application_detail', args=[self.application.pk]),
        )
        self.assertFalse(storage.exists(name))

    def test_user_cannot_create_document_for_another_users_application(self):
        self.client.login(username='metadatauser', password='testpass123')

        response = self.client.post(
            reverse('document_create', args=[self.other_application.pk]),
            self.document_form_data()
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            ApplicationDocument.objects.filter(
                user=self.user,
                application=self.other_application
            ).exists()
        )

    def test_document_link_requires_http_or_https(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('document_create', args=[self.application.pk]),
            self.document_form_data(link='ftp://example.com/private-cv'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Enter a valid document link using http:// or https://.')

    def test_owner_can_delete_document_metadata(self):
        self.client.login(username='metadatauser', password='testpass123')

        response = self.client.post(reverse('document_delete', args=[self.document.pk]))

        self.assertRedirects(
            response,
            reverse('application_detail', args=[self.application.pk])
        )
        self.assertFalse(ApplicationDocument.objects.filter(pk=self.document.pk).exists())

    def test_owner_can_update_document_metadata(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('document_update', args=[self.document.pk]),
            self.document_form_data(title='Updated CV'),
        )

        self.assertRedirects(
            response,
            reverse('application_detail', args=[self.application.pk])
        )
        self.document.refresh_from_db()
        self.assertEqual(self.document.title, 'Updated CV')

    def test_user_cannot_update_another_users_document(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('document_update', args=[self.hidden_document.pk]),
            self.document_form_data(title='Changed'),
        )

        self.assertEqual(response.status_code, 404)
        self.hidden_document.refresh_from_db()
        self.assertEqual(self.hidden_document.title, 'Hidden CV')

    def test_user_cannot_delete_another_users_document(self):
        self.client.login(username='metadatauser', password='testpass123')

        response = self.client.post(reverse('document_delete', args=[self.hidden_document.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(ApplicationDocument.objects.filter(pk=self.hidden_document.pk).exists())

    def test_owner_can_create_reminder(self):
        self.client.login(username='metadatauser', password='testpass123')

        response = self.client.post(
            reverse('reminder_create', args=[self.application.pk]),
            self.reminder_form_data()
        )

        self.assertRedirects(
            response,
            reverse('application_detail', args=[self.application.pk])
        )
        self.assertTrue(
            Reminder.objects.filter(
                user=self.user,
                application=self.application,
                title='Send follow-up email'
            ).exists()
        )

    def test_user_cannot_create_reminder_for_another_users_application(self):
        self.client.login(username='metadatauser', password='testpass123')

        response = self.client.post(
            reverse('reminder_create', args=[self.other_application.pk]),
            self.reminder_form_data()
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            Reminder.objects.filter(
                user=self.user,
                application=self.other_application
            ).exists()
        )

    def test_owner_can_update_reminder(self):
        self.client.login(username='metadatauser', password='testpass123')

        response = self.client.post(
            reverse('reminder_update', args=[self.reminder.pk]),
            self.reminder_form_data(title='Updated follow-up')
        )

        self.assertRedirects(
            response,
            reverse('application_detail', args=[self.application.pk])
        )
        self.reminder.refresh_from_db()
        self.assertEqual(self.reminder.title, 'Updated follow-up')

    def test_reminder_edit_form_formats_existing_datetime(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('reminder_update', args=[self.reminder.pk]))
        expected_value = django_timezone.localtime(self.reminder.due_at).strftime('%Y-%m-%dT%H:%M')

        self.assertContains(response, f'value="{expected_value}"')

    def test_user_cannot_update_another_users_reminder(self):
        self.client.login(username='metadatauser', password='testpass123')

        response = self.client.post(
            reverse('reminder_update', args=[self.hidden_reminder.pk]),
            self.reminder_form_data(title='Changed')
        )

        self.assertEqual(response.status_code, 404)
        self.hidden_reminder.refresh_from_db()
        self.assertEqual(self.hidden_reminder.title, 'Hidden reminder')

    def test_owner_can_delete_reminder(self):
        self.client.login(username='metadatauser', password='testpass123')

        response = self.client.post(reverse('reminder_delete', args=[self.reminder.pk]))

        self.assertRedirects(
            response,
            reverse('application_detail', args=[self.application.pk])
        )
        self.assertFalse(Reminder.objects.filter(pk=self.reminder.pk).exists())

    def test_user_cannot_delete_another_users_reminder(self):
        self.client.login(username='metadatauser', password='testpass123')

        response = self.client.post(reverse('reminder_delete', args=[self.hidden_reminder.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Reminder.objects.filter(pk=self.hidden_reminder.pk).exists())

    def test_documents_and_reminders_appear_on_application_detail(self):
        self.client.login(username='metadatauser', password='testpass123')

        response = self.client.get(reverse('application_detail', args=[self.application.pk]))

        self.assertContains(response, 'CV Backend v2')
        self.assertContains(response, 'Follow up')
        self.assertNotContains(response, 'Hidden CV')
        self.assertNotContains(response, 'Hidden reminder')

    def test_dashboard_shows_upcoming_reminders(self):
        self.client.login(username='metadatauser', password='testpass123')

        response = self.client.get(reverse('dashboard'))

        self.assertContains(response, 'Upcoming Reminders')
        self.assertContains(response, 'Follow up')
        self.assertNotContains(response, 'Hidden reminder')


class JobApplicationSearchFilterTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='searchuser',
            password='testpass123'
        )
        self.other_user = User.objects.create_user(
            username='othersearchuser',
            password='testpass123'
        )
        self.google = JobApplication.objects.create(
            user=self.user,
            company='Google',
            job_title='Software Engineer',
            location='London',
            employment_type='full_time',
            status='applied',
            application_date='2026-09-01'
        )
        self.amazon = JobApplication.objects.create(
            user=self.user,
            company='Amazon',
            job_title='Backend Developer',
            location='Manchester',
            employment_type='contract',
            status='interview',
            application_date='2026-09-10'
        )
        self.remote_saved = JobApplication.objects.create(
            user=self.user,
            company='Remote Works',
            job_title='Product Analyst',
            location='Remote',
            employment_type='part_time',
            status='saved',
            application_date='2026-09-15'
        )
        self.hidden = JobApplication.objects.create(
            user=self.other_user,
            company='Hidden Google',
            job_title='Developer Advocate',
            location='Remote',
            employment_type='contract',
            status='interview',
            application_date='2026-09-10'
        )

    def test_search_by_company(self):
        self.client.login(username='searchuser', password='testpass123')

        response = self.client.get(reverse('application_list'), {'search': 'Google'})

        self.assertContains(response, self.google.company)
        self.assertNotContains(response, self.amazon.company)

    def test_search_by_job_title(self):
        self.client.login(username='searchuser', password='testpass123')

        response = self.client.get(
            reverse('application_list'),
            {'search': 'Developer'}
        )

        self.assertContains(response, self.amazon.company)
        self.assertNotContains(response, self.google.company)

    def test_search_by_location(self):
        self.client.login(username='searchuser', password='testpass123')

        response = self.client.get(reverse('application_list'), {'search': 'Remote'})

        self.assertContains(response, self.remote_saved.company)
        self.assertNotContains(response, self.google.company)

    def test_search_is_case_insensitive(self):
        self.client.login(username='searchuser', password='testpass123')

        response = self.client.get(reverse('application_list'), {'search': 'google'})

        self.assertContains(response, self.google.company)

    def test_filter_by_status(self):
        self.client.login(username='searchuser', password='testpass123')

        response = self.client.get(
            reverse('application_list'),
            {'status': 'interview'}
        )

        self.assertContains(response, self.amazon.company)
        self.assertNotContains(response, self.google.company)

    def test_search_and_status_filter_work_together(self):
        self.client.login(username='searchuser', password='testpass123')

        response = self.client.get(
            reverse('application_list'),
            {'search': 'developer', 'status': 'interview'}
        )

        self.assertContains(response, self.amazon.company)
        self.assertNotContains(response, self.google.company)
        self.assertNotContains(response, self.remote_saved.company)

    def test_filter_by_employment_type(self):
        self.client.login(username='searchuser', password='testpass123')

        response = self.client.get(
            reverse('application_list'),
            {'employment_type': 'contract'}
        )

        self.assertContains(response, self.amazon.company)
        self.assertNotContains(response, self.google.company)
        self.assertNotContains(response, self.hidden.company)

    def test_filter_by_date_from(self):
        self.client.login(username='searchuser', password='testpass123')

        response = self.client.get(
            reverse('application_list'),
            {'date_from': '2026-09-09'}
        )

        self.assertContains(response, self.amazon.company)
        self.assertContains(response, self.remote_saved.company)
        self.assertNotContains(response, self.google.company)

    def test_filter_by_date_to(self):
        self.client.login(username='searchuser', password='testpass123')

        response = self.client.get(
            reverse('application_list'),
            {'date_to': '2026-09-09'}
        )

        self.assertContains(response, self.google.company)
        self.assertNotContains(response, self.amazon.company)

    def test_search_status_type_and_date_filters_work_together(self):
        self.client.login(username='searchuser', password='testpass123')

        response = self.client.get(
            reverse('application_list'),
            {
                'search': 'developer',
                'status': 'interview',
                'employment_type': 'contract',
                'date_from': '2026-09-01',
                'date_to': '2026-09-30',
            }
        )

        self.assertContains(response, self.amazon.company)
        self.assertNotContains(response, self.google.company)
        self.assertNotContains(response, self.hidden.company)

    def test_invalid_employment_type_filter_is_ignored(self):
        self.client.login(username='searchuser', password='testpass123')

        response = self.client.get(
            reverse('application_list'),
            {'employment_type': 'not-real'}
        )

        self.assertContains(response, self.google.company)
        self.assertContains(response, self.amazon.company)
        self.assertContains(response, self.remote_saved.company)

    def test_no_query_shows_all_current_users_applications(self):
        self.client.login(username='searchuser', password='testpass123')

        response = self.client.get(reverse('application_list'))

        self.assertContains(response, self.google.company)
        self.assertContains(response, self.amazon.company)
        self.assertContains(response, self.remote_saved.company)
        self.assertNotContains(response, self.hidden.company)

    def test_search_never_exposes_another_users_applications(self):
        self.client.login(username='searchuser', password='testpass123')

        response = self.client.get(reverse('application_list'), {'search': 'Hidden'})

        self.assertNotContains(response, self.hidden.company)
        self.assertContains(response, 'No applications match your search.')

    def test_no_matching_results_show_search_empty_message(self):
        self.client.login(username='searchuser', password='testpass123')

        response = self.client.get(reverse('application_list'), {'search': 'Nothing'})

        self.assertContains(response, 'No applications match your search.')
        self.assertNotContains(response, 'No job applications found.')

    def test_anonymous_user_is_redirected_to_login_for_search(self):
        response = self.client.get(reverse('application_list'), {'search': 'Google'})

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])

    def test_status_filter_auto_submits_when_changed(self):
        self.client.login(username='searchuser', password='testpass123')

        response = self.client.get(reverse('application_list'))

        self.assertContains(
            response,
            '<select name="status" onchange="this.form.submit()" aria-label="Filter by status">'
        )

    def test_sort_filter_auto_submits_when_changed(self):
        self.client.login(username='searchuser', password='testpass123')

        response = self.client.get(reverse('application_list'))

        self.assertContains(
            response,
            '<select name="sort" onchange="this.form.submit()" aria-label="Sort applications">'
        )


class JobApplicationSortingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(
            username='sortuser',
            password='testpass123'
        )
        cls.other_user = User.objects.create_user(
            username='othersortuser',
            password='testpass123'
        )
        cls.alpha = JobApplication.objects.create(
            user=cls.user,
            company='Alpha Apps',
            job_title='Python Developer',
            location='London',
            status='applied'
        )
        cls.beta = JobApplication.objects.create(
            user=cls.user,
            company='Beta Labs',
            job_title='Backend Developer',
            location='Manchester',
            status='interview'
        )
        cls.gamma = JobApplication.objects.create(
            user=cls.user,
            company='Gamma Group',
            job_title='Frontend Developer',
            location='Remote',
            status='interview'
        )
        cls.hidden = JobApplication.objects.create(
            user=cls.other_user,
            company='Zeta Secret',
            job_title='Backend Developer',
            location='Remote',
            status='interview'
        )

        JobApplication.objects.filter(pk=cls.alpha.pk).update(
            created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc)
        )
        JobApplication.objects.filter(pk=cls.beta.pk).update(
            created_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
            updated_at=datetime(2026, 9, 5, tzinfo=timezone.utc)
        )
        JobApplication.objects.filter(pk=cls.gamma.pk).update(
            created_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
            updated_at=datetime(2026, 9, 4, tzinfo=timezone.utc)
        )
        JobApplication.objects.filter(pk=cls.hidden.pk).update(
            created_at=datetime(2026, 9, 6, tzinfo=timezone.utc),
            updated_at=datetime(2026, 9, 6, tzinfo=timezone.utc)
        )

    def application_companies(self, params=None):
        self.client.force_login(self.user)
        response = self.client.get(reverse('application_list'), params or {})
        return [job.company for job in response.context['applications']]

    def test_newest_first(self):
        companies = self.application_companies({'sort': 'newest'})

        self.assertEqual(companies, ['Gamma Group', 'Beta Labs', 'Alpha Apps'])

    def test_oldest_first(self):
        companies = self.application_companies({'sort': 'oldest'})

        self.assertEqual(companies, ['Alpha Apps', 'Beta Labs', 'Gamma Group'])

    def test_recently_updated(self):
        companies = self.application_companies({'sort': 'updated'})

        self.assertEqual(companies, ['Beta Labs', 'Gamma Group', 'Alpha Apps'])

    def test_company_a_to_z(self):
        companies = self.application_companies({'sort': 'company_az'})

        self.assertEqual(companies, ['Alpha Apps', 'Beta Labs', 'Gamma Group'])

    def test_company_z_to_a(self):
        companies = self.application_companies({'sort': 'company_za'})

        self.assertEqual(companies, ['Gamma Group', 'Beta Labs', 'Alpha Apps'])

    def test_sorting_works_with_search(self):
        companies = self.application_companies({
            'search': 'developer',
            'sort': 'company_za',
        })

        self.assertEqual(companies, ['Gamma Group', 'Beta Labs', 'Alpha Apps'])

    def test_sorting_works_with_status_filter(self):
        companies = self.application_companies({
            'status': 'interview',
            'sort': 'company_az',
        })

        self.assertEqual(companies, ['Beta Labs', 'Gamma Group'])

    def test_sorting_works_with_search_and_status_filter(self):
        companies = self.application_companies({
            'search': 'developer',
            'status': 'interview',
            'sort': 'newest',
        })

        self.assertEqual(companies, ['Gamma Group', 'Beta Labs'])

    def test_invalid_sort_parameter_falls_back_to_newest(self):
        companies = self.application_companies({'sort': 'not-real'})

        self.assertEqual(companies, ['Gamma Group', 'Beta Labs', 'Alpha Apps'])

    def test_sorting_never_exposes_another_users_applications(self):
        companies = self.application_companies({
            'search': 'developer',
            'status': 'interview',
            'sort': 'company_az',
        })

        self.assertEqual(companies, ['Beta Labs', 'Gamma Group'])
        self.assertNotIn('Zeta Secret', companies)

    def test_anonymous_user_is_redirected_to_login_for_sorting(self):
        response = self.client.get(reverse('application_list'), {'sort': 'oldest'})

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])


class JobApplicationPaginationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(
            username='pageuser',
            password='testpass123'
        )
        cls.other_user = User.objects.create_user(
            username='otherpageuser',
            password='testpass123'
        )

        for number in range(1, 13):
            application = JobApplication.objects.create(
                user=cls.user,
                company=f'Page Company {number:02}',
                job_title='Backend Developer',
                location='Remote',
                employment_type='contract',
                status='interview' if number <= 11 else 'saved',
                application_date=f'2026-09-{number:02}'
            )
            JobApplication.objects.filter(pk=application.pk).update(
                created_at=datetime(2026, 9, number, tzinfo=timezone.utc),
                updated_at=datetime(2026, 9, number, tzinfo=timezone.utc)
            )

        cls.hidden = JobApplication.objects.create(
            user=cls.other_user,
                company='Hidden Page Company',
                job_title='Backend Developer',
                location='Remote',
                employment_type='contract',
                status='interview',
                application_date='2026-09-13'
            )
        JobApplication.objects.filter(pk=cls.hidden.pk).update(
            created_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
            updated_at=datetime(2026, 9, 13, tzinfo=timezone.utc)
        )

    def get_list(self, params=None):
        self.client.force_login(self.user)
        return self.client.get(reverse('application_list'), params or {})

    def test_first_page_contains_ten_applications(self):
        response = self.get_list()

        self.assertEqual(len(response.context['applications']), 10)
        self.assertContains(response, 'Page 1 of 2')

    def test_second_page_works(self):
        response = self.get_list({'page': 2})

        self.assertEqual(response.context['page_obj'].number, 2)
        self.assertEqual(len(response.context['applications']), 2)

    def test_previous_and_next_behavior_works(self):
        first_page = self.get_list()
        second_page = self.get_list({'page': 2})

        self.assertTrue(first_page.context['page_obj'].has_next())
        self.assertFalse(first_page.context['page_obj'].has_previous())
        self.assertTrue(second_page.context['page_obj'].has_previous())
        self.assertFalse(second_page.context['page_obj'].has_next())

    def test_search_parameter_is_preserved_across_pages(self):
        response = self.get_list({'search': 'Developer'})

        self.assertContains(response, 'search=Developer&amp;page=2')

    def test_status_filter_is_preserved_across_pages(self):
        response = self.get_list({'status': 'interview'})

        self.assertContains(response, 'status=interview&amp;page=2')

    def test_employment_type_filter_is_preserved_across_pages(self):
        response = self.get_list({'employment_type': 'contract'})

        self.assertContains(response, 'employment_type=contract&amp;page=2')

    def test_date_filters_are_preserved_across_pages(self):
        response = self.get_list({
            'date_from': '2026-09-01',
            'date_to': '2026-09-11',
        })

        self.assertContains(response, 'date_from=2026-09-01&amp;date_to=2026-09-11&amp;page=2')

    def test_sorting_is_preserved_across_pages(self):
        response = self.get_list({'sort': 'oldest'})

        self.assertContains(response, 'sort=oldest&amp;page=2')

    def test_search_status_sorting_and_pagination_work_together(self):
        response = self.get_list({
            'search': 'Developer',
            'status': 'interview',
            'employment_type': 'contract',
            'date_from': '2026-09-01',
            'date_to': '2026-09-11',
            'sort': 'oldest',
            'page': 2,
        })
        companies = [job.company for job in response.context['applications']]

        self.assertEqual(companies, ['Page Company 11'])
        self.assertContains(
            response,
            'search=Developer&amp;status=interview&amp;employment_type=contract&amp;date_from=2026-09-01&amp;date_to=2026-09-11&amp;sort=oldest&amp;page=1'
        )

    def test_invalid_page_values_do_not_crash(self):
        bad_text = self.get_list({'page': 'abc'})
        too_large = self.get_list({'page': 99999})
        negative = self.get_list({'page': -5})

        self.assertEqual(bad_text.status_code, 200)
        self.assertEqual(too_large.status_code, 200)
        self.assertEqual(negative.status_code, 200)

    def test_pagination_never_exposes_another_users_applications(self):
        response = self.get_list({
            'search': 'Developer',
            'sort': 'newest',
        })

        self.assertNotContains(response, self.hidden.company)

    def test_no_pagination_controls_when_results_fit_on_one_page(self):
        response = self.get_list({'status': 'saved'})

        self.assertNotContains(response, 'Page 1 of')
        self.assertNotContains(response, 'Next')
        self.assertNotContains(response, 'Previous')

    def test_anonymous_user_is_redirected_to_login_for_pagination(self):
        response = self.client.get(reverse('application_list'), {'page': 2})

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])


class JobApplicationFormValidationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='formuser',
            password='testpass123'
        )
        self.other_user = User.objects.create_user(
            username='otherformuser',
            password='testpass123'
        )
        self.existing_application = JobApplication.objects.create(
            user=self.user,
            company='Original Company',
            job_title='Original Title',
            location='Original Location',
            status='saved'
        )

    def valid_form_data(self, **overrides):
        data = {
            'company': 'Example Company',
            'job_title': 'Python Developer',
            'location': 'Remote',
            'job_url': 'https://example.com/job',
            'employment_type': 'full_time',
            'work_mode': 'remote',
            'source': 'LinkedIn',
            'recruiter_name': 'Alex Recruiter',
            'recruiter_email': 'alex@example.com',
            'status': 'applied',
            'salary_min': '2500',
            'salary_max': '3000',
            'currency': 'EUR',
            'application_date': django_timezone.localdate(),
            'deadline': django_timezone.localdate() + timedelta(days=7),
            'notes': 'Follow up next week.',
        }
        data.update(overrides)
        return data

    def test_empty_company_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(company=''))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['company'], ['Company name is required.'])

    def test_whitespace_only_company_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(company='     '))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['company'], ['Company name is required.'])

    def test_one_character_company_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(company='A'))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['company'], ['Company name must be at least 2 characters.'])

    def test_empty_job_title_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(job_title=''))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['job_title'], ['Job title is required.'])

    def test_whitespace_only_job_title_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(job_title='     '))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['job_title'], ['Job title is required.'])

    def test_one_character_job_title_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(job_title='B'))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['job_title'], ['Job title must be at least 2 characters.'])

    def test_blank_location_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(location=''))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['location'], ['Location is required.'])

    def test_whitespace_only_location_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(location='     '))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['location'], ['Location is required.'])

    def test_legacy_salary_field_is_not_user_editable(self):
        form = JobApplicationForm()

        self.assertNotIn('salary', form.fields)

    def test_blank_application_date_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(application_date=''))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['application_date'], ['Application date is required.'])

    def test_invalid_url_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(job_url='not a url'))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['job_url'], ['Enter a valid job URL.'])

    def test_non_http_job_url_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(job_url='ftp://example.com/job'))

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors['job_url'],
            ['Enter a valid job URL using http:// or https://.'],
        )

    def test_blank_url_allowed(self):
        form = JobApplicationForm(data=self.valid_form_data(job_url=''))

        self.assertTrue(form.is_valid())

    def test_negative_salary_min_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(salary_min='-1'))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['salary_min'], ['Salary minimum cannot be negative.'])

    def test_negative_salary_max_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(salary_max='-1'))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['salary_max'], ['Salary maximum cannot be negative.'])

    def test_salary_max_lower_than_salary_min_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(salary_min='3000', salary_max='2500'))

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors['salary_max'],
            ['Salary maximum must be greater than or equal to salary minimum.']
        )

    def test_blank_structured_salary_fields_allowed(self):
        form = JobApplicationForm(data=self.valid_form_data(salary_min='', salary_max=''))

        self.assertTrue(form.is_valid())

    def test_invalid_recruiter_email_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(recruiter_email='not an email'))

        self.assertFalse(form.is_valid())
        self.assertIn('recruiter_email', form.errors)

    def test_optional_recruiter_fields_can_be_blank(self):
        form = JobApplicationForm(
            data=self.valid_form_data(recruiter_name='', recruiter_email='')
        )

        self.assertTrue(form.is_valid())

    def test_deadline_before_application_date_rejected(self):
        today = django_timezone.localdate()
        form = JobApplicationForm(
            data=self.valid_form_data(application_date=today, deadline=today - timedelta(days=1))
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['deadline'], ['Deadline cannot be before the application date.'])

    def test_tomorrow_application_date_rejected(self):
        tomorrow = django_timezone.localdate() + timedelta(days=1)
        form = JobApplicationForm(
            data=self.valid_form_data(application_date=tomorrow)
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors['application_date'],
            ['Application date cannot be in the future.']
        )

    def test_today_application_date_allowed(self):
        form = JobApplicationForm(
            data=self.valid_form_data(application_date=django_timezone.localdate())
        )

        self.assertTrue(form.is_valid())

    def test_yesterday_application_date_allowed(self):
        yesterday = django_timezone.localdate() - timedelta(days=1)
        form = JobApplicationForm(
            data=self.valid_form_data(application_date=yesterday)
        )

        self.assertTrue(form.is_valid())

    def test_project_uses_lithuania_timezone(self):
        self.assertEqual(settings.TIME_ZONE, 'Europe/Vilnius')

    def test_valid_form_creates_application(self):
        self.client.login(username='formuser', password='testpass123')

        response = self.client.post(
            reverse('application_create'),
            self.valid_form_data(company='  Trimmed Company  ')
        )

        self.assertRedirects(response, reverse('application_list'))
        self.assertTrue(
            JobApplication.objects.filter(
                user=self.user,
                company='Trimmed Company'
            ).exists()
        )
        created_application = JobApplication.objects.get(
            user=self.user,
            company='Trimmed Company',
        )
        self.assertEqual(created_application.salary, '')
        self.assertEqual(created_application.recruiter_name, 'Alex Recruiter')
        self.assertEqual(created_application.recruiter_email, 'alex@example.com')

    def test_invalid_edit_does_not_corrupt_existing_application(self):
        self.client.login(username='formuser', password='testpass123')

        response = self.client.post(
            reverse('application_update', args=[self.existing_application.pk]),
            self.valid_form_data(company='', job_title='Changed Title')
        )

        self.assertEqual(response.status_code, 200)
        self.existing_application.refresh_from_db()
        self.assertEqual(self.existing_application.company, 'Original Company')
        self.assertEqual(self.existing_application.job_title, 'Original Title')

    def test_valid_edit_status_change_creates_history(self):
        self.client.login(username='formuser', password='testpass123')

        response = self.client.post(
            reverse('application_update', args=[self.existing_application.pk]),
            self.valid_form_data(status='interview')
        )

        self.assertRedirects(response, reverse('application_list'))
        self.assertTrue(
            StatusHistory.objects.filter(
                user=self.user,
                application=self.existing_application,
                old_status='saved',
                new_status='interview'
            ).exists()
        )

    def test_validation_does_not_weaken_edit_ownership(self):
        self.client.login(username='otherformuser', password='testpass123')

        response = self.client.post(
            reverse('application_update', args=[self.existing_application.pk]),
            self.valid_form_data(company='')
        )

        self.assertEqual(response.status_code, 404)
        self.existing_application.refresh_from_db()
        self.assertEqual(self.existing_application.company, 'Original Company')

    def test_application_form_uses_browser_required_validation(self):
        self.client.login(username='formuser', password='testpass123')

        response = self.client.get(reverse('application_create'))

        self.assertContains(response, '<form method="POST" class="form-card">')
        self.assertNotContains(response, 'novalidate')
        self.assertContains(response, 'name="company"')
        self.assertContains(response, 'required')

    def test_multiple_validation_errors_show_together(self):
        self.client.login(username='formuser', password='testpass123')

        response = self.client.post(
            reverse('application_create'),
            self.valid_form_data(company='', job_url='not a url')
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Company name is required.')
        self.assertContains(response, 'Enter a valid job URL.')


class PublicSeoTests(TestCase):
    def test_public_pages_have_metadata_and_canonical_without_query_string(self):
        for name in ('home', 'about', 'privacy'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name) + '?tracking=ignored')
                self.assertContains(response, '<meta name="robots" content="index, follow">')
                self.assertContains(response, '<meta name="description"')
                self.assertContains(response, '<meta property="og:title"')
                self.assertContains(response, '<meta property="og:url"')
                self.assertContains(
                    response,
                    f'<link rel="canonical" href="http://testserver{reverse(name)}">',
                )
                self.assertNotContains(response, 'tracking=ignored')

    def test_private_and_authentication_pages_are_not_indexable(self):
        self.assertContains(
            self.client.get(reverse('login')),
            '<meta name="robots" content="noindex, nofollow">',
        )
        User = get_user_model()
        user = User.objects.create_user(username='seo-user', password='testpass123')
        self.client.force_login(user)
        for name in ('dashboard', 'application_list', 'profile', 'kanban_board'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, '<meta name="robots" content="noindex, nofollow">')
                self.assertNotContains(response, '<link rel="canonical"')

    def test_sitemap_lists_only_public_pages(self):
        response = self.client.get(reverse('sitemap'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/xml')
        for name in ('home', 'about', 'privacy'):
            self.assertContains(response, f'https://testserver{reverse(name)}')
        for private_path in ('/dashboard/', '/applications/', '/accounts/', '/interviews/'):
            self.assertNotContains(response, private_path)

    def test_robots_lists_sitemap_and_disallows_private_paths(self):
        response = self.client.get(reverse('robots_txt'))
        self.assertContains(response, 'Disallow: /applications/')
        self.assertContains(response, 'Disallow: /accounts/')
        self.assertContains(response, 'Sitemap: http://testserver/sitemap.xml')
        self.assertEqual(response['Content-Type'], 'text/plain; charset=utf-8')
