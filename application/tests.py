from datetime import datetime, timezone

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
            status='interview',
            salary='50000',
            application_date='2026-09-01',
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
        self.assertContains(response, 'Interview')
        self.assertContains(response, '50000')
        self.assertContains(response, 'Prepare for technical interview.')

    def test_nonexistent_application_detail_returns_404(self):
        self.client.login(username='detailowner', password='testpass123')

        response = self.client.get(reverse('application_detail', args=[99999]))

        self.assertEqual(response.status_code, 404)


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
            status='applied'
        )
        self.amazon = JobApplication.objects.create(
            user=self.user,
            company='Amazon',
            job_title='Backend Developer',
            location='Manchester',
            status='interview'
        )
        self.remote_saved = JobApplication.objects.create(
            user=self.user,
            company='Remote Works',
            job_title='Product Analyst',
            location='Remote',
            status='saved'
        )
        self.hidden = JobApplication.objects.create(
            user=self.other_user,
            company='Hidden Google',
            job_title='Developer Advocate',
            location='Remote',
            status='interview'
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
