import json
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from .models import ApplicationDocument, JobApplication
from .services import job_import, lever
from .test_job_import import FIXTURE, PUBLIC_ADDRESS, posting_html, response_mock


POSTING_ID = '5ac21346-8e0c-4494-8e7a-3eb92ff77902'
LEVER_URL = f'https://jobs.lever.co/example-site/{POSTING_ID}?lever-source=tracker'
EU_URL = f'https://jobs.eu.lever.co/example-site/{POSTING_ID}'
API_URL = f'https://api.lever.co/v0/postings/example-site/{POSTING_ID}?mode=json'
EU_API_URL = f'https://api.eu.lever.co/v0/postings/example-site/{POSTING_ID}?mode=json'
PAGE = (Path(settings.BASE_DIR) / 'tests/fixtures/lever_posting.html').read_text(encoding='utf-8')


def job_payload():
    return json.loads((Path(settings.BASE_DIR) / 'tests/fixtures/lever_posting.json').read_text(encoding='utf-8'))


class LeverAdapterTests(SimpleTestCase):
    def import_payload(self, payload, url=LEVER_URL, html=PAGE):
        with patch.object(job_import.time, 'monotonic', return_value=10):
            with patch.object(job_import, 'fetch_public_json', return_value=payload) as api:
                with patch.object(job_import, 'fetch_public_html', return_value=(html, url)) as page:
                    result = job_import.import_job_details(url)
        root = EU_API_URL if 'jobs.eu.lever.co' in url else API_URL
        api.assert_called_once_with(root, deadline=14)
        if payload.get('text'):
            page.assert_called_once_with(url, deadline=18)
        return result

    def test_global_posting_maps_supported_fields_without_saving(self):
        result = self.import_payload(job_payload())
        self.assertEqual(result['data'], {
            'company': 'Example Engineering', 'job_title': 'Backend Engineer', 'location': 'Europe',
            'work_mode': 'remote', 'employment_type': 'full_time', 'salary_min': '50000.00',
            'salary_max': '60000.00', 'currency': 'EUR', 'source': 'Lever', 'job_url': LEVER_URL,
        })
        self.assertEqual(set(result['imported_fields']), set(result['data']))
        self.assertIn('per year', ' '.join(result['warnings']))
        for field in ('status', 'application_date', 'notes', 'cv_file', 'recruiter_email', 'description'):
            self.assertNotIn(field, result['data'])

    def test_eu_url_uses_eu_api(self):
        result = self.import_payload(job_payload(), EU_URL)
        self.assertEqual(result['data']['company'], 'Example Engineering')
        self.assertEqual(result['data']['job_url'], EU_URL)
        self.assertEqual(result['data']['source'], 'Lever')

    def test_queries_fragments_and_trailing_slashes_preserve_exact_url(self):
        for url in (LEVER_URL + '&ref=review#application', EU_URL + '/?lever-source=tracker#apply'):
            with self.subTest(url=url):
                self.assertEqual(self.import_payload(job_payload(), url)['data']['job_url'], url)

    def test_invalid_ids_sites_and_lookalike_hosts_use_generic_not_api(self):
        for url in (
            LEVER_URL.replace(POSTING_ID, 'invalid'), LEVER_URL.replace(POSTING_ID, '12345'),
            LEVER_URL.replace(POSTING_ID, '00000000-0000-0000-0000-000000000000'),
            LEVER_URL.replace('example-site', '..'), LEVER_URL.replace('example-site', '%2e%2e'),
            LEVER_URL.replace('example-site/', ''), LEVER_URL.replace('example-site', '-invalid'),
            LEVER_URL.replace(POSTING_ID, POSTING_ID + '/apply'),
            LEVER_URL.replace('jobs.lever.co', 'jobs.lever.co.evil.example.com'),
            EU_URL.replace('jobs.eu.lever.co', 'jobs.eu.lever.co.evil.example.com'),
        ):
            with self.subTest(url=url), patch.object(job_import, 'fetch_public_json') as api:
                with patch.object(job_import, 'fetch_public_html', return_value=(FIXTURE, url)) as generic:
                    result = job_import.import_job_details(url)
                api.assert_not_called()
                generic.assert_called_once_with(url)
                self.assertEqual(result['data']['job_url'], url)

    def test_credentials_and_unsupported_schemes_rejected_before_network(self):
        for url in (LEVER_URL.replace('https://', 'ftp://'), LEVER_URL.replace('https://', 'https://user:password@')):
            with self.subTest(url=url), patch.object(job_import, 'fetch_public_json') as api:
                with patch.object(job_import, 'fetch_public_html') as page:
                    with self.assertRaises(job_import.JobImportError):
                        job_import.import_job_details(url)
                api.assert_not_called()
                page.assert_not_called()

    def test_unknown_site_api_failure_uses_generic_with_total_deadline(self):
        url = LEVER_URL.replace('example-site', 'unknown-site')
        with patch.object(job_import.time, 'monotonic', return_value=10):
            with patch.object(job_import, 'fetch_public_json', side_effect=job_import.JobImportError()) as api:
                with patch.object(job_import, 'fetch_public_html', return_value=(FIXTURE, url)) as page:
                    data = job_import.import_job_details(url)['data']
        api.assert_called_once_with(API_URL.replace('example-site', 'unknown-site'), deadline=14)
        page.assert_called_once_with(url, deadline=18)
        self.assertEqual(data['source'], 'Lever')
        self.assertEqual(data['job_url'], url)

    def test_bad_responses_fall_back_safely(self):
        for payload in (None, [], {}, {'id': True}, {'id': 'different'}, {'id': POSTING_ID}):
            with self.subTest(payload=payload), patch.object(job_import, 'fetch_public_json', return_value=payload):
                with patch.object(job_import, 'fetch_public_html', return_value=(FIXTURE, LEVER_URL)) as page:
                    self.assertEqual(job_import.import_job_details(LEVER_URL)['data']['job_url'], LEVER_URL)
                page.assert_called_once()

    def test_generic_fallback_preserves_lever_source_after_safe_public_redirect(self):
        with patch.object(job_import, 'fetch_public_json', side_effect=job_import.JobImportError()):
            with patch.object(job_import, 'fetch_public_html', return_value=(FIXTURE, 'https://careers.example.com/job')):
                data = job_import.import_job_details(LEVER_URL)['data']
        self.assertEqual(data['job_url'], LEVER_URL)
        self.assertEqual(data['source'], 'Lever')

    def test_missing_fields_and_untrustworthy_company_stay_blank(self):
        data = self.import_payload({'id': POSTING_ID, 'text': 'Backend Engineer'}, html='<title>Careers</title>')['data']
        self.assertEqual(data, {'job_title': 'Backend Engineer', 'source': 'Lever', 'job_url': LEVER_URL})
        self.assertNotIn('company', data)

    def test_missing_company_page_does_not_discard_api_values(self):
        with patch.object(job_import, 'fetch_public_json', return_value=job_payload()):
            with patch.object(job_import, 'fetch_public_html', side_effect=job_import.JobImportError()):
                result = job_import.import_job_details(LEVER_URL)
        self.assertNotIn('company', result['data'])
        self.assertEqual(result['data']['job_title'], 'Backend Engineer')
        self.assertEqual(result['data']['currency'], 'EUR')
        self.assertIn('remaining fields manually', ' '.join(result['warnings']))

    def test_company_metadata_title_requires_exact_api_role(self):
        for html, expected in (
            ('<title>Acme &amp; Co - Backend Engineer</title>', 'Acme & Co'),
            ('<meta property="og:title" content="Acme &amp; Co - Backend Engineer">', 'Acme & Co'),
            ('<title>Acme Co - Backend Engineer</title><meta property="og:title" content="Other Co - Backend Engineer">', None),
            ('<title>Acme Co - Another role</title>', None),
            ('<title>Just a moment...</title>' + PAGE, None),
        ):
            with self.subTest(html=html):
                self.assertEqual(self.import_payload(job_payload(), html=html)['data'].get('company'), expected)

    def test_structured_company_requires_matching_role_and_same_final_listing(self):
        wrong_role = posting_html({'@type': 'JobPosting', 'title': 'Another role', 'hiringOrganization': {'name': 'Wrong Co'}})
        self.assertNotIn('company', self.import_payload(job_payload(), html=wrong_role)['data'])
        with patch.object(job_import, 'fetch_public_json', return_value=job_payload()):
            with patch.object(job_import, 'fetch_public_html', return_value=(PAGE, LEVER_URL.replace(POSTING_ID, '11111111-1111-1111-1111-111111111111'))):
                self.assertNotIn('company', job_import.import_job_details(LEVER_URL)['data'])

    def test_wrong_listing_and_conflicting_structured_company_are_not_guessed(self):
        posting = {'@type': 'JobPosting', 'title': 'Backend Engineer', 'hiringOrganization': {'name': 'Wrong Co'}}
        wrong_url = dict(posting, url=LEVER_URL.replace(POSTING_ID, '11111111-1111-1111-1111-111111111111'))
        self.assertNotIn('company', self.import_payload(job_payload(), html=posting_html(wrong_url))['data'])
        conflicting = [posting, dict(posting, hiringOrganization={'name': 'Another Co'})]
        self.assertNotIn('company', self.import_payload(job_payload(), html=posting_html(conflicting))['data'])

    def test_company_structured_graph_and_malformed_json_use_existing_parser(self):
        posting = {'@type': 'JobPosting', 'title': 'Backend Engineer', 'hiringOrganization': {'name': 'ACME Corp'}}
        html = '<script type="application/ld+json">{broken}</script>' + posting_html({'@graph': [posting]})
        self.assertEqual(self.import_payload(job_payload(), html=html)['data']['company'], 'ACME Corp')

    def test_company_title_matching_does_not_truncate_unicode_names(self):
        self.assertEqual(lever.company_from_titles(['ACME & Co - Stra\u00dfe Engineer'], 'STRASSE Engineer'), '')
        self.assertEqual(lever.company_from_titles(['ACME & Co - Backend Engineer'], 'backend engineer'), 'ACME & Co')

    def test_employment_commitments_only_map_known_choices(self):
        for value, expected in (
            ('Full-time', 'full_time'), ('Fulltime', 'full_time'), ('Full Time', 'full_time'),
            ('Part-time', 'part_time'), ('Parttime', 'part_time'), ('Contract', 'contract'),
            ('Temporary', 'temporary'), ('Internship', 'internship'), ('Flexible', None),
            (['Full-time', 'Part-time'], None), ({'label': 'Full-time'}, None),
        ):
            with self.subTest(value=value):
                payload = job_payload()
                payload['categories']['commitment'] = value
                self.assertEqual(self.import_payload(payload)['data'].get('employment_type'), expected)

    def test_explicit_employment_content_when_commitment_missing(self):
        payload = job_payload()
        payload['categories'].pop('commitment')
        payload['description'] = '<p>Employment type: Contract</p>'
        self.assertEqual(self.import_payload(payload)['data']['employment_type'], 'contract')

    def test_workplace_type_and_location_normalization(self):
        for location, mode, geography in (
            ('Remote - Europe', 'remote', 'Europe'), ('Hybrid - London', 'hybrid', 'London'),
            ('On-site in Berlin', 'onsite', 'Berlin'), ('Vilnius, Lithuania - Hybrid', 'hybrid', 'Vilnius, Lithuania'),
            ('Remote', 'remote', 'Remote'), ('Berlin, Germany', None, 'Berlin, Germany'),
        ):
            with self.subTest(location=location):
                payload = job_payload()
                payload['workplaceType'] = 'unspecified'
                payload['categories']['location'] = location
                data = self.import_payload(payload)['data']
                self.assertEqual(data.get('work_mode'), mode)
                self.assertEqual(data['location'], geography)

    def test_structured_workplace_has_priority(self):
        for workplace, expected in (('remote', 'remote'), ('hybrid', 'hybrid'), ('on-site', 'onsite')):
            with self.subTest(workplace=workplace):
                payload = job_payload()
                payload['workplaceType'] = workplace
                payload['categories']['location'] = 'Berlin, Germany'
                payload['description'] = '<p>This is a remote position.</p>'
                self.assertEqual(self.import_payload(payload)['data']['work_mode'], expected)

    def test_explicit_work_mode_content_and_ambiguous_wording(self):
        for content, expected in (
            ('Remote', 'remote'), ('Fully remote', 'remote'), ('Hybrid', 'hybrid'),
            ('Hybrid role', 'hybrid'), ('On-site', 'onsite'), ('Onsite', 'onsite'), ('Office-based', 'onsite'),
            ('Remote collaboration with an international team.', None),
            ('Occasional work from home and a flexible workplace.', None),
            ('This is not a hybrid role.', None), ('This role is remote if needed.', None),
            ('<p>Remote</p><p>Hybrid</p>', None),
        ):
            with self.subTest(content=content):
                payload = job_payload()
                payload['workplaceType'] = 'unspecified'
                payload['categories']['location'] = 'Berlin, Germany'
                payload['description'] = f'<div>{content}</div>'
                self.assertEqual(self.import_payload(payload)['data'].get('work_mode'), expected)

    def test_all_locations_used_only_when_primary_missing(self):
        payload = job_payload()
        payload['workplaceType'] = 'hybrid'
        payload['categories']['allLocations'] = ['London, UK', 'Berlin, Germany']
        payload['categories']['location'] = 'Vilnius, Lithuania'
        self.assertEqual(self.import_payload(payload)['data']['location'], 'Vilnius, Lithuania')
        payload['categories'].pop('location')
        self.assertEqual(self.import_payload(payload)['data']['location'], 'London, UK / Berlin, Germany')

    def test_structured_salary_preferred_over_content(self):
        payload = job_payload()
        payload['salaryRange'] = {'min': 120000, 'max': 140000, 'currency': 'USD', 'interval': 'per-year-salary'}
        payload['description'] = '<p>Salary: 50000 - 60000 EUR</p>'
        data = self.import_payload(payload)['data']
        self.assertEqual(data['salary_min'], '120000.00')
        self.assertEqual(data['salary_max'], '140000.00')
        self.assertEqual(data['currency'], 'USD')

    def test_labelled_salary_fallback_and_reliable_currency_only(self):
        for text, expected_currency, minimum, maximum in (
            ('Salary: $120,000 - $140,000', None, '120000.00', '140000.00'),
            ('Compensation: \u20ac50,000\u2013\u20ac60,000', 'EUR', '50000.00', '60000.00'),
            ('Pay range: \u00a345,000 - \u00a355,000', 'GBP', '45000.00', '55000.00'),
            ('Salary: 3000 - 4000 gross per month', None, '3000.00', '4000.00'),
        ):
            with self.subTest(text=text):
                payload = job_payload()
                payload.pop('salaryRange')
                payload['description'] = f'<p>{text}</p>'
                data = self.import_payload(payload)['data']
                self.assertEqual(data['salary_min'], minimum)
                self.assertEqual(data['salary_max'], maximum)
                self.assertEqual(data.get('currency'), expected_currency)

    def test_plain_salary_description_and_labelled_list_section(self):
        for fields in (
            {'salaryDescriptionPlain': 'Compensation:\nEUR 50000 - 60000 per year'},
            {'lists': [{'text': 'Salary range', 'content': '<li>EUR 50000 - 60000 per year</li>'}]},
        ):
            with self.subTest(fields=fields):
                payload = dict(job_payload(), salaryRange=None, **fields)
                self.assertEqual(self.import_payload(payload)['data']['salary_min'], '50000.00')

    def test_absent_salary_unrelated_numbers_and_ambiguous_ranges_stay_blank(self):
        for content in (
            '', '<p>1000 employees, a 50000 bonus fund, and 60000 customers.</p>',
            '<p>$120,000 - $140,000</p>', '<script>Salary: 50000 - 60000 EUR</script>',
            '<p>Salary: 50000 - 60000 EUR</p><p>Salary: 80000 - 90000 USD</p>',
        ):
            with self.subTest(content=content):
                payload = dict(job_payload(), salaryRange=None, description=content)
                data = self.import_payload(payload)['data']
                for field in ('salary_min', 'salary_max', 'currency'):
                    self.assertNotIn(field, data)

    def test_structured_salary_without_currency_stays_blank(self):
        payload = job_payload()
        payload['salaryRange'].pop('currency')
        data = self.import_payload(payload)['data']
        self.assertEqual(data['salary_min'], '50000.00')
        self.assertNotIn('currency', data)

    def test_invalid_or_multiple_structured_salary_ranges_are_not_guessed(self):
        for salary in (
            {'min': 60000, 'max': 50000}, {'min': True, 'max': -1},
            {'min': 'NaN', 'max': 'Infinity'}, {'min': '1' * 100, 'max': None},
            [{'min': 50000, 'max': 60000}, {'min': 80000, 'max': 90000}],
        ):
            with self.subTest(salary=salary):
                payload = dict(job_payload(), salaryRange=salary, description='<p>Salary: 50000 - 60000 EUR</p>')
                data = self.import_payload(payload)['data']
                for field in ('salary_min', 'salary_max', 'currency'):
                    self.assertNotIn(field, data)

    def test_optional_company_fetch_must_stay_on_same_lever_listing(self):
        for final in ('https://careers.example.com/job', EU_URL, LEVER_URL.replace('example-site', 'another-site')):
            with self.subTest(final=final), patch.object(job_import, 'fetch_public_json', return_value=job_payload()):
                with patch.object(job_import, 'fetch_public_html', return_value=(PAGE, final)):
                    self.assertNotIn('company', job_import.import_job_details(LEVER_URL)['data'])


class LeverNetworkTests(SimpleTestCase):
    def test_both_regions_use_public_validation_and_pinned_connections(self):
        for url, host in ((LEVER_URL, 'api.lever.co'), (EU_URL, 'api.eu.lever.co')):
            with self.subTest(url=url), patch.object(job_import.time, 'monotonic', return_value=10):
                with patch.object(job_import, 'resolve_public_host', return_value=PUBLIC_ADDRESS) as resolve:
                    with patch.object(job_import, 'PublicConnection') as connection:
                        connection.return_value.getresponse.side_effect = [
                            response_mock(json.dumps(job_payload()).encode(), headers={'Content-Type': 'application/json'}),
                            response_mock(PAGE.encode()),
                        ]
                        data = job_import.import_job_details(url)['data']
                self.assertEqual(resolve.call_args_list[0].args, (host, 443, 14))
                self.assertEqual(resolve.call_args_list[1].args, (url.split('/')[2], 443, 18))
                self.assertEqual(connection.call_args_list[0].args[2], PUBLIC_ADDRESS)
                request = connection.return_value.request.call_args_list[0]
                self.assertEqual(request.args, ('GET', f'/v0/postings/example-site/{POSTING_ID}?mode=json'))
                self.assertEqual(request.kwargs['headers']['Accept'], 'application/json')
                self.assertNotIn('Authorization', request.kwargs['headers'])
                self.assertNotIn('Cookie', request.kwargs['headers'])
                self.assertEqual(data['company'], 'Example Engineering')

    def test_lever_api_rejects_unsafe_responses(self):
        for url in (API_URL, EU_API_URL):
            for response in (
                response_mock(status=302, headers={'Location': 'http://169.254.169.254/latest/meta-data'}),
                response_mock(b'{}', headers={'Content-Type': 'text/html'}),
                response_mock(b'{broken', headers={'Content-Type': 'application/json'}),
                response_mock(headers={'Content-Type': 'application/json', 'Content-Length': str(job_import.MAX_RESPONSE_BYTES + 1)}),
                response_mock(b'x' * (job_import.MAX_RESPONSE_BYTES + 1), headers={'Content-Type': 'application/json'}),
            ):
                with self.subTest(url=url), patch.object(job_import, 'resolve_public_host', return_value=PUBLIC_ADDRESS):
                    with patch.object(job_import, 'PublicConnection') as connection:
                        connection.return_value.getresponse.return_value = response
                        with self.assertRaises(job_import.JobImportError):
                            job_import.fetch_public_json(url)

    def test_lever_api_private_dns_and_timeouts_remain_blocked(self):
        private = (PUBLIC_ADDRESS[0], PUBLIC_ADDRESS[1], 6, '', ('10.0.0.1', 443))
        for url in (API_URL, EU_API_URL):
            with self.subTest(url=url), patch.object(job_import.socket, 'getaddrinfo', return_value=[PUBLIC_ADDRESS, private]):
                with patch.object(job_import, 'PublicConnection') as connection:
                    with self.assertRaises(job_import.JobImportError):
                        job_import.fetch_public_json(url)
                    connection.assert_not_called()
            with patch.object(job_import, 'resolve_public_host', return_value=PUBLIC_ADDRESS):
                with patch.object(job_import, 'PublicConnection') as connection:
                    connection.return_value.getresponse.return_value = response_mock(headers={'Content-Type': 'application/json'})
                    connection.return_value.getresponse.return_value.read1.side_effect = TimeoutError('internal details')
                    with self.assertRaisesMessage(job_import.JobImportError, job_import.MANUAL_MESSAGE):
                        job_import.fetch_public_json(url)


class LeverEndpointTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='lever-reviewer')
        self.client.force_login(self.user)

    def test_import_returns_review_data_without_creating_private_records(self):
        with patch.object(job_import, 'fetch_public_json', return_value=job_payload()):
            with patch.object(job_import, 'fetch_public_html', return_value=(PAGE, LEVER_URL)):
                response = self.client.post(reverse('application_import'), {'url': LEVER_URL})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertEqual(response.json()['data']['company'], 'Example Engineering')
        self.assertEqual(response.json()['data']['source'], 'Lever')
        self.assertEqual(JobApplication.objects.count(), 0)
        self.assertEqual(ApplicationDocument.objects.count(), 0)

    def test_import_keeps_authentication_post_and_csrf_requirements(self):
        endpoint = reverse('application_import')
        with patch.object(job_import, 'fetch_public_json') as api:
            self.assertEqual(Client().post(endpoint, {'url': LEVER_URL}).status_code, 302)
            self.assertEqual(self.client.get(endpoint).status_code, 405)
            csrf_client = Client(enforce_csrf_checks=True)
            csrf_client.force_login(self.user)
            self.assertEqual(csrf_client.post(endpoint, {'url': LEVER_URL}).status_code, 403)
            api.assert_not_called()

    def test_failed_api_and_page_have_only_friendly_error(self):
        with patch.object(job_import, 'fetch_public_json', side_effect=job_import.JobImportError()):
            with patch.object(job_import, 'fetch_public_html', side_effect=job_import.JobImportError()):
                response = self.client.post(reverse('application_import'), {'url': LEVER_URL})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['message'], job_import.MANUAL_MESSAGE)
        self.assertEqual(JobApplication.objects.count(), 0)
