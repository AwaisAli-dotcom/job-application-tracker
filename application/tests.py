from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone as django_timezone

from .forms import JobApplicationForm
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
        self.assertRedirects(response, reverse('dashboard'))
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
            status='saved'
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
            application_date=today
        )

    def test_home_page_is_public(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Job Application Tracker')

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
        self.assertEqual(response.context['interviews_count'], 1)
        self.assertEqual(response.context['offers_count'], 1)
        self.assertEqual(response.context['interview_rate'], 50)
        self.assertEqual(response.context['offer_rate'], 50)
        self.assertContains(response, 'Interview Company')
        self.assertNotContains(response, 'Hidden Dashboard Company')

    def test_empty_dashboard_has_helpful_empty_state(self):
        empty_user = get_user_model().objects.create_user(
            username='emptydashboarduser',
            password='testpass123'
        )
        self.client.force_login(empty_user)

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No applications yet')


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
            status='applied'
        )
        self.hidden_application = JobApplication.objects.create(
            user=self.other_user,
            company='Hidden Kanban Company',
            job_title='Secret Developer',
            location='Remote',
            status='interview'
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

    def test_status_update_fallback_redirects_to_kanban(self):
        self.client.login(username='kanbanuser', password='testpass123')

        response = self.client.post(
            reverse('application_status_update', args=[self.application.pk]),
            {'status': 'technical_test'}
        )

        self.assertRedirects(response, reverse('kanban_board'))
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'technical_test')

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
            '<select name="status" onchange="this.form.submit()">'
        )

    def test_sort_filter_auto_submits_when_changed(self):
        self.client.login(username='searchuser', password='testpass123')

        response = self.client.get(reverse('application_list'))

        self.assertContains(
            response,
            '<select name="sort" onchange="this.form.submit()">'
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
            'status': 'applied',
            'salary': '2500-3000 EUR',
            'application_date': django_timezone.localdate(),
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

    def test_empty_job_title_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(job_title=''))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['job_title'], ['Job title is required.'])

    def test_whitespace_only_job_title_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(job_title='     '))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['job_title'], ['Job title is required.'])

    def test_blank_location_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(location=''))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['location'], ['Location is required.'])

    def test_whitespace_only_location_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(location='     '))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['location'], ['Location is required.'])

    def test_blank_salary_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(salary=''))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['salary'], ['Salary is required.'])

    def test_blank_application_date_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(application_date=''))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['application_date'], ['Application date is required.'])

    def test_invalid_url_rejected(self):
        form = JobApplicationForm(data=self.valid_form_data(job_url='not a url'))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['job_url'], ['Enter a valid job URL.'])

    def test_blank_url_allowed(self):
        form = JobApplicationForm(data=self.valid_form_data(job_url=''))

        self.assertTrue(form.is_valid())

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
