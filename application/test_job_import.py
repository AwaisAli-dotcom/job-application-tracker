import json
import socket
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import ApplicationDocument, JobApplication
from .services import job_import


FIXTURE = (Path(settings.BASE_DIR) / 'tests/fixtures/job_posting.html').read_text(encoding='utf-8')
PUBLIC_URL = 'https://careers.example.com/jobs/python?ref=tracker'
PUBLIC_ADDRESS = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))


def posting_html(value):
    return '<script type="application/ld+json">' + json.dumps(value) + '</script>'


def response_mock(body=b'<html></html>', status=200, headers=None):
    response = MagicMock()
    response.status = status
    response.headers = Message()
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    for key, value in (headers or {}).items():
        if key in response.headers:
            del response.headers[key]
        response.headers[key] = value
    response.getheader.side_effect = lambda name, default=None: response.headers.get(name, default)
    response.read1.side_effect = [body, b'']
    return response


class JobImportParsingTests(SimpleTestCase):
    def test_structured_job_imports_supported_fields(self):
        result = job_import.parse_job_html(FIXTURE, PUBLIC_URL)
        self.assertEqual(result['data'], {
            'company': 'Example Engineering', 'job_title': 'Python Developer',
            'location': 'Vilnius, Lithuania / Remote', 'work_mode': 'remote',
            'employment_type': 'full_time', 'salary_min': '2500.00',
            'salary_max': '3500.00', 'currency': 'USD',
            'source': 'Example Engineering careers', 'job_url': PUBLIC_URL,
        })
        self.assertIn('per month', ' '.join(result['warnings']))
        self.assertEqual(set(result['imported_fields']), set(result['data']))
        self.assertNotIn('notes', result['data'])

    def test_arrays_graphs_and_multiple_script_blocks(self):
        posting = {'@type': ['Thing', 'JobPosting'], 'title': 'Engineer'}
        for value in ([posting], {'@graph': [{'@type': 'Organization'}, posting]}):
            with self.subTest(value=value):
                html = posting_html({'@type': 'WebSite'}) + posting_html(value)
                self.assertEqual(job_import.parse_job_html(html, PUBLIC_URL)['data']['job_title'], 'Engineer')

    def test_malformed_json_does_not_hide_valid_later_script(self):
        html = '<script type="application/ld+json">{broken}</script>' + FIXTURE
        self.assertEqual(job_import.parse_job_html(html, PUBLIC_URL)['data']['company'], 'Example Engineering')

    def test_missing_job_posting_uses_only_explicit_metadata_title(self):
        html = '<meta property="og:title" content="Backend Engineer at Example Company">'
        result = job_import.parse_job_html(html, PUBLIC_URL)
        self.assertEqual(result['data']['job_title'], 'Backend Engineer')
        self.assertEqual(result['data']['company'], 'Example Company')
        self.assertNotIn('location', result['data'])
        self.assertTrue(result['warnings'])

    def test_html_title_fallback(self):
        result = job_import.parse_job_html('<title>Developer at Example Company</title>', PUBLIC_URL)
        self.assertEqual(result['data']['job_title'], 'Developer')

    def test_metadata_completes_compatible_structured_fields(self):
        html = '<title>Engineer at Example Company</title>' + posting_html({'@type': 'JobPosting', 'title': 'Engineer'})
        self.assertEqual(job_import.parse_job_html(html, PUBLIC_URL)['data']['company'], 'Example Company')
        html = '<title>Other role at Different Company</title>' + posting_html({'@type': 'JobPosting', 'title': 'Engineer'})
        self.assertNotIn('company', job_import.parse_job_html(html, PUBLIC_URL)['data'])

    def test_unreasonable_metadata_values_are_bounded(self):
        self.assertEqual(job_import.clean_text('<' * 100000, 120), '')
        self.assertEqual(job_import.salary_number('1' * 100000), '')
        html = posting_html([{'@type': 'JobPosting', 'title': 'Engineer', 'url': f'https://example.com/{index}'} for index in range(101)])
        with self.assertRaises(job_import.JobImportError):
            job_import.parse_job_html(html, PUBLIC_URL)

    def test_missing_fields_are_not_invented(self):
        result = job_import.parse_job_html(posting_html({'@type': 'JobPosting', 'title': 'Engineer'}), PUBLIC_URL)
        for field in ('company', 'location', 'employment_type', 'work_mode', 'salary_min', 'currency'):
            self.assertNotIn(field, result['data'])

    def test_generic_and_protected_pages_fail_gracefully(self):
        for html in ('<title>Careers</title>', '<title>Jobs at Example</title>',
                     '<title>Just a moment...</title>' + FIXTURE,
                     '<title>Sign in</title>', posting_html({'@type': 'Organization'})):
            with self.subTest(html=html[:50]):
                with self.assertRaisesMessage(job_import.JobImportError, job_import.MANUAL_MESSAGE):
                    job_import.parse_job_html(html, PUBLIC_URL)

    def test_multiple_jobs_require_an_exact_listing_match(self):
        first = {'@type': 'JobPosting', 'title': 'Wrong role', 'url': 'https://careers.example.com/jobs/other'}
        second = {'@type': 'JobPosting', 'title': 'Right role', 'url': PUBLIC_URL}
        html = posting_html([first, second])
        self.assertEqual(job_import.parse_job_html(html, PUBLIC_URL)['data']['job_title'], 'Right role')
        with self.assertRaises(job_import.JobImportError):
            job_import.parse_job_html(html, 'https://careers.example.com/jobs/')

    def test_canonical_matches_same_listing_without_tracking_query(self):
        canonical = 'https://careers.example.com/jobs/python'
        html = '<link rel="canonical" href="' + canonical + '">' + posting_html([
            {'@type': 'JobPosting', 'title': 'Right role', 'url': canonical},
            {'@type': 'JobPosting', 'title': 'Wrong role', 'url': 'https://careers.example.com/jobs/other'},
        ])
        result = job_import.parse_job_html(html, PUBLIC_URL)
        self.assertEqual(result['data']['job_title'], 'Right role')
        self.assertEqual(result['data']['job_url'], PUBLIC_URL)

    def test_employment_mapping_is_conservative(self):
        for value, expected in (
            ('FULL_TIME', 'full_time'), ('PART_TIME', 'part_time'),
            ('CONTRACTOR', 'contract'), ('TEMPORARY', 'temporary'), ('INTERN', 'internship'),
            ('UNKNOWN', None), (['FULL_TIME', 'PART_TIME'], None),
        ):
            with self.subTest(value=value):
                data, _ = job_import.normalize_job({'employmentType': value})
                self.assertEqual(data.get('employment_type'), expected)

    def test_remote_applicant_country_and_onsite_location(self):
        data, _ = job_import.normalize_job({
            'jobLocationType': 'TELECOMMUTE',
            'applicantLocationRequirements': {'@type': 'Country', 'name': 'Germany'},
        })
        self.assertEqual(data['location'], 'Germany / Remote')
        self.assertEqual(data['work_mode'], 'remote')
        data, _ = job_import.normalize_job({'jobLocation': {'address': {'addressLocality': 'Berlin', 'addressCountry': 'DE'}}})
        self.assertEqual(data['location'], 'Berlin, Germany')
        self.assertNotIn('work_mode', data)

    def test_remote_without_country_does_not_invent_a_country(self):
        data, _ = job_import.normalize_job({'jobLocationType': 'TELECOMMUTE'})
        self.assertEqual(data['location'], 'Remote')

    def test_work_mode_needs_explicit_structured_evidence(self):
        for value, expected in (('HYBRID', 'hybrid'), ('ON_SITE', 'onsite')):
            data, _ = job_import.normalize_job({'jobLocationType': value})
            self.assertEqual(data['work_mode'], expected)
        data, _ = job_import.normalize_job({'description': 'Remote and hybrid working options'})
        self.assertNotIn('work_mode', data)

    def test_single_salary_and_invalid_salary_values(self):
        data, warnings = job_import.normalize_job({'baseSalary': {'currency': 'EUR', 'value': 3000}})
        self.assertEqual(data['salary_min'], '3000.00')
        self.assertNotIn('salary_max', data)
        self.assertTrue(warnings)
        for value in ('NaN', 'Infinity', '-1', '10000000000', '12.345', True, '€3000'):
            with self.subTest(value=value):
                self.assertEqual(job_import.salary_number(value), '')

    def test_invalid_salary_range_is_not_imported(self):
        data, warnings = job_import.normalize_job({'baseSalary': {'currency': 'EUR', 'value': {'minValue': 5000, 'maxValue': 3000}}})
        self.assertNotIn('salary_min', data)
        self.assertNotIn('currency', data)
        self.assertTrue(warnings)

    def test_provider_sources_use_domain_boundaries(self):
        for host, expected in (
            ('www.linkedin.com', 'LinkedIn'), ('www.indeed.com', 'Indeed'),
            ('boards.greenhouse.io', 'Greenhouse'), ('jobs.lever.co', 'Lever'),
            ('company.myworkdayjobs.com', 'Workday'), ('jobs.ashbyhq.com', 'Ashby'),
            ('linkedin.com.evil.example.com', 'linkedin.com.evil.example.com'),
        ):
            with self.subTest(host=host):
                self.assertEqual(job_import.source_name('https://' + host + '/job'), expected)

    def test_structured_text_is_cleaned_and_overlong_fields_are_omitted(self):
        data, _ = job_import.normalize_job({'title': '<b>Engineer</b>', 'hiringOrganization': {'name': 'x' * 121}})
        self.assertEqual(data['job_title'], 'Engineer')
        self.assertNotIn('company', data)


class JobImportNetworkTests(SimpleTestCase):
    def test_unsafe_urls_are_rejected_before_any_connection(self):
        urls = (
            'http://localhost/job', 'http://127.0.0.1/job', 'http://127.7.8.9/job',
            'http://[::1]/job', 'http://10.0.0.1/job', 'http://172.16.1.1/job',
            'http://192.168.1.1/job', 'http://[fc00::1]/job', 'http://[fe80::1]/job',
            'http://169.254.169.254/latest/meta-data', 'http://168.63.129.16/job',
            'http://[::ffff:127.0.0.1]/job', 'http://224.0.0.1/job',
            'http://100.64.0.1/job', 'http://0.0.0.0/job', 'http://192.0.2.1/job',
            'https://user:password@example.com/job', 'file:///etc/passwd',
            'ftp://example.com/job', 'data:text/html,job', 'javascript:alert(1)',
            'http://intranet/job', 'http://company.internal/job', 'http://metadata.google.internal/job',
            'https://example.com:8080/job', 'https://example.com\\@127.0.0.1/job',
            'https://example.com/\r\nX-Test:secret', 'https://[::1',
        )
        with patch.object(job_import, 'PublicConnection') as connection:
            for url in urls:
                with self.subTest(url=url):
                    with self.assertRaises(job_import.JobImportError):
                        job_import.fetch_public_html(url)
            connection.assert_not_called()

    def test_all_dns_results_must_be_public(self):
        for ip in ('10.0.0.1', '169.254.169.254', '127.0.0.1', 'fc00::1'):
            private = (socket.AF_INET6 if ':' in ip else socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443))
            with self.subTest(ip=ip), patch.object(job_import.socket, 'getaddrinfo', return_value=[PUBLIC_ADDRESS, private]):
                with patch.object(job_import, 'PublicConnection') as connection:
                    with self.assertRaises(job_import.JobImportError):
                        job_import.fetch_public_html(PUBLIC_URL)
                    connection.assert_not_called()

    def test_dns_failure_is_friendly(self):
        with patch.object(job_import.socket, 'getaddrinfo', side_effect=socket.gaierror('internal detail')):
            with self.assertRaisesMessage(job_import.JobImportError, job_import.MANUAL_MESSAGE):
                job_import.fetch_public_html(PUBLIC_URL)

    def test_dns_timeout_is_bounded(self):
        with patch.object(job_import.queue.Queue, 'get', side_effect=job_import.queue.Empty):
            with patch.object(job_import.socket, 'getaddrinfo', return_value=[PUBLIC_ADDRESS]):
                with self.assertRaisesMessage(job_import.JobImportError, job_import.MANUAL_MESSAGE):
                    job_import.fetch_public_html(PUBLIC_URL)

    def test_connection_uses_pinned_ip_and_verifies_original_tls_hostname(self):
        with patch.object(job_import.socket, 'socket') as sock, patch.object(job_import.ssl, 'create_default_context') as context:
            with patch.object(job_import.socket, 'getaddrinfo') as resolve:
                connection = job_import.PublicConnection('careers.example.com', 443, PUBLIC_ADDRESS, 'https', job_import.time.monotonic() + 8)
                connection.connect()
                sock.return_value.connect.assert_called_once_with(PUBLIC_ADDRESS[4])
                context.return_value.wrap_socket.assert_called_once_with(sock.return_value, server_hostname='careers.example.com')
                resolve.assert_not_called()

    def fetch_with_response(self, response):
        with patch.object(job_import, 'resolve_public_host', return_value=PUBLIC_ADDRESS):
            with patch.object(job_import, 'PublicConnection') as connection:
                connection.return_value.getresponse.return_value = response
                result = job_import.fetch_public_html(PUBLIC_URL)
                self.assertEqual(connection.call_args.args[2], PUBLIC_ADDRESS)
                headers = connection.return_value.request.call_args.kwargs['headers']
                self.assertNotIn('Cookie', headers)
                self.assertNotIn('Authorization', headers)
                self.assertEqual(headers['Accept-Encoding'], 'identity')
                return result

    def test_valid_html_is_fetched_with_bounded_plain_response(self):
        html, url = self.fetch_with_response(response_mock(FIXTURE.encode()))
        self.assertEqual(html, FIXTURE)
        self.assertEqual(url, PUBLIC_URL)

    def test_redirect_to_private_destination_is_rejected(self):
        response = response_mock(status=302, headers={'Location': 'http://169.254.169.254/secret'})
        with self.assertRaises(job_import.JobImportError):
            self.fetch_with_response(response)

    def test_redirect_hostname_is_resolved_and_validated_again(self):
        public = [PUBLIC_ADDRESS]
        private = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.5', 443))]
        with patch.object(job_import.socket, 'getaddrinfo', side_effect=[public, private]) as resolve:
            with patch.object(job_import, 'PublicConnection') as connection:
                connection.return_value.getresponse.return_value = response_mock(status=302, headers={'Location': 'https://redirect.example.com/job'})
                with self.assertRaises(job_import.JobImportError):
                    job_import.fetch_public_html(PUBLIC_URL)
                self.assertEqual(resolve.call_count, 2)
                self.assertEqual(connection.call_count, 1)

    def test_excessive_redirects_are_rejected(self):
        response = response_mock(status=302, headers={'Location': '/another-job'})
        with patch.object(job_import, 'resolve_public_host', return_value=PUBLIC_ADDRESS):
            with patch.object(job_import, 'PublicConnection') as connection:
                connection.return_value.getresponse.return_value = response
                with self.assertRaises(job_import.JobImportError):
                    job_import.fetch_public_html(PUBLIC_URL)
                self.assertEqual(connection.call_count, job_import.MAX_REDIRECTS + 1)

    def test_public_redirect_is_fetched_without_cookies(self):
        with patch.object(job_import, 'resolve_public_host', return_value=PUBLIC_ADDRESS) as resolve:
            with patch.object(job_import, 'PublicConnection') as connection:
                connection.return_value.getresponse.side_effect = [
                    response_mock(status=302, headers={'Location': '/jobs/redirected', 'Set-Cookie': 'private=value'}),
                    response_mock(FIXTURE.encode()),
                ]
                html, url = job_import.fetch_public_html(PUBLIC_URL)
                self.assertEqual(url, 'https://careers.example.com/jobs/redirected')
                self.assertEqual(html, FIXTURE)
                self.assertEqual(resolve.call_count, 2)
                self.assertNotIn('Cookie', connection.return_value.request.call_args.kwargs['headers'])

    def test_total_deadline_rejects_slow_response(self):
        with patch.object(job_import.time, 'monotonic', side_effect=[0, 0, 0, 9]):
            with patch.object(job_import.threading, 'Timer'):
                with self.assertRaisesMessage(job_import.JobImportError, job_import.MANUAL_MESSAGE):
                    self.fetch_with_response(response_mock())

    def test_oversized_body_is_rejected_even_without_length_header(self):
        with self.assertRaises(job_import.JobImportError):
            self.fetch_with_response(response_mock(b'x' * (job_import.MAX_RESPONSE_BYTES + 1)))

    def test_oversized_content_length_is_rejected_before_reading(self):
        response = response_mock(headers={'Content-Length': str(job_import.MAX_RESPONSE_BYTES + 1)})
        with self.assertRaises(job_import.JobImportError):
            self.fetch_with_response(response)
        response.read1.assert_not_called()

    def test_non_html_compressed_and_blocked_responses_are_rejected(self):
        for response in (
            response_mock(headers={'Content-Type': 'application/pdf'}),
            response_mock(headers={'Content-Encoding': 'gzip'}),
            response_mock(status=403), response_mock(status=429),
        ):
            with self.subTest(response=response):
                with self.assertRaisesMessage(job_import.JobImportError, job_import.MANUAL_MESSAGE):
                    self.fetch_with_response(response)

    def test_network_timeout_does_not_expose_exception(self):
        response = response_mock()
        response.read1.side_effect = TimeoutError('secret internal network details')
        with self.assertRaisesMessage(job_import.JobImportError, job_import.MANUAL_MESSAGE):
            self.fetch_with_response(response)

    def test_redirect_retains_original_job_url(self):
        with patch.object(job_import, 'fetch_public_html', return_value=(FIXTURE, 'https://jobs.lever.co/example/123')):
            result = job_import.import_job_details(PUBLIC_URL)
        self.assertEqual(result['data']['job_url'], PUBLIC_URL)
        self.assertEqual(result['data']['source'], 'Lever')


class JobImportEndpointTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='importuser', password='testpass123')
        self.client.force_login(self.user)
        self.url = reverse('application_import')

    def test_anonymous_import_redirects_to_login(self):
        self.client.logout()
        response = self.client.post(self.url, {'url': PUBLIC_URL})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('login')))

    def test_get_cannot_import(self):
        with patch('application.views.import_job_details') as importer:
            response = self.client.get(self.url, {'url': PUBLIC_URL})
        self.assertEqual(response.status_code, 405)
        importer.assert_not_called()

    def test_csrf_is_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(self.url, {'url': PUBLIC_URL})
        self.assertEqual(response.status_code, 403)
        client.get(reverse('application_create'))
        with patch('application.views.import_job_details', return_value=job_import.parse_job_html(FIXTURE, PUBLIC_URL)):
            response = client.post(self.url, {'url': PUBLIC_URL}, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)

    def test_import_returns_data_without_creating_application_or_document(self):
        with patch.object(job_import, 'fetch_public_html', return_value=(FIXTURE, PUBLIC_URL)):
            response = self.client.post(self.url, {'url': PUBLIC_URL})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertEqual(response.json()['data']['company'], 'Example Engineering')
        self.assertEqual(JobApplication.objects.count(), 0)
        self.assertEqual(ApplicationDocument.objects.count(), 0)
        self.assertNotIn('<html', response.content.decode())

    def test_invalid_urls_never_reach_fetcher(self):
        with patch('application.views.import_job_details') as importer:
            for url in ('', 'http://127.0.0.1/', 'https://user:secret@example.com/job', 'x' * 201):
                response = self.client.post(self.url, {'url': url})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['message'], job_import.URL_MESSAGE)
        importer.assert_not_called()

    def test_failed_import_still_allows_manual_creation(self):
        with patch('application.views.import_job_details', side_effect=job_import.JobImportError()):
            response = self.client.post(self.url, {'url': PUBLIC_URL})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['message'], job_import.MANUAL_MESSAGE)
        response = self.client.post(reverse('application_create'), {
            'company': 'Manual Company', 'job_title': 'Engineer', 'location': 'Vilnius',
            'status': 'saved', 'application_date': timezone.localdate(), 'job_url': PUBLIC_URL,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(JobApplication.objects.get().company, 'Manual Company')

    def test_unexpected_failure_does_not_leak_internal_details(self):
        with patch('application.views.import_job_details', side_effect=RuntimeError('private-network-secret')):
            response = self.client.post(self.url, {'url': PUBLIC_URL})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['message'], job_import.MANUAL_MESSAGE)
        self.assertNotContains(response, 'private-network-secret', status_code=502)

    def test_imports_are_limited_per_user(self):
        result = job_import.parse_job_html(FIXTURE, PUBLIC_URL)
        with patch('application.views.import_job_details', return_value=result) as importer:
            for _ in range(10):
                self.assertEqual(self.client.post(self.url, {'url': PUBLIC_URL}).status_code, 200)
            response = self.client.post(self.url, {'url': PUBLIC_URL})
            self.assertEqual(response.status_code, 429)
            self.assertIn('Retry-After', response)
            self.assertEqual(importer.call_count, 10)
            other = get_user_model().objects.create_user(username='otherimportuser')
            self.client.force_login(other)
            self.assertEqual(self.client.post(self.url, {'url': PUBLIC_URL}).status_code, 200)

    def test_import_controls_are_add_only(self):
        response = self.client.get(reverse('application_create'))
        self.assertContains(response, 'data-job-import=')
        application = JobApplication.objects.create(user=self.user, company='Existing', job_title='Engineer', application_date=timezone.localdate())
        response = self.client.get(reverse('application_update', args=[application.pk]))
        self.assertNotContains(response, 'data-job-import=')
