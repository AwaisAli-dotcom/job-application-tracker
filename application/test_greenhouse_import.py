import json
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import ApplicationDocument, JobApplication
from .services import greenhouse, job_import
from .test_job_import import FIXTURE, PUBLIC_ADDRESS, response_mock


GREENHOUSE_URL = 'https://job-boards.greenhouse.io/drivewealth/jobs/5869146003?gh_jid=5869146003'
API_URL = 'https://boards-api.greenhouse.io/v1/boards/drivewealth/jobs/5869146003?pay_transparency=true'
EU_URL = 'https://job-boards.eu.greenhouse.io/pinecagroup/jobs/4988463101?gh_jid=4988463101'
EU_API_URL = 'https://boards-api.greenhouse.io/v1/boards/pinecagroup/jobs/4988463101?pay_transparency=true'


def job_payload():
    return json.loads((Path(settings.BASE_DIR) / 'tests/fixtures/greenhouse_job.json').read_text(encoding='utf-8'))


class GreenhouseAdapterTests(SimpleTestCase):
    def import_payload(self, payload):
        with patch.object(job_import, 'fetch_public_json', return_value=payload) as fetch:
            with patch.object(job_import, 'fetch_public_html') as generic:
                result = job_import.import_job_details(GREENHOUSE_URL)
        generic.assert_not_called()
        self.assertEqual(fetch.call_args.args, (API_URL,))
        return result

    def test_exact_drivewealth_listing(self):
        result = self.import_payload(job_payload())
        self.assertEqual(result['data'], {
            'company': 'DriveWealth',
            'job_title': 'Senior Accountant, Broker-Dealer Accounting',
            'location': 'Office - NYC', 'job_url': GREENHOUSE_URL, 'source': 'Greenhouse',
        })
        self.assertEqual(set(result['imported_fields']), set(result['data']))
        self.assertEqual(result['warnings'], [])

    def test_query_and_fragment_are_preserved_but_not_sent_to_api(self):
        url = GREENHOUSE_URL + '&ref=review#application'
        with patch.object(job_import, 'fetch_public_json', return_value=job_payload()) as fetch:
            result = job_import.import_job_details(url)
        self.assertEqual(fetch.call_args.args, (API_URL,))
        self.assertEqual(result['data']['job_url'], url)

    def test_legacy_host_and_trailing_slash(self):
        url = 'https://boards.greenhouse.io/drivewealth/jobs/5869146003/'
        self.assertEqual(greenhouse.job_reference(url), ('drivewealth', '5869146003'))
        with patch.object(job_import, 'fetch_public_json', return_value=job_payload()):
            self.assertEqual(job_import.import_job_details(url)['data']['job_url'], url)

    def test_eu_host_uses_public_api_and_preserves_pasted_url(self):
        payload = dict(job_payload(), id=4988463101, company_name='Pineca Group')
        for url in (EU_URL, EU_URL.split('?')[0], EU_URL + '&ref=review#application'):
            with self.subTest(url=url), patch.object(job_import, 'fetch_public_json', return_value=payload) as fetch:
                with patch.object(job_import, 'fetch_public_html') as generic:
                    result = job_import.import_job_details(url)
                self.assertEqual(greenhouse.job_reference(url), ('pinecagroup', '4988463101'))
                self.assertEqual(fetch.call_args.args, (EU_API_URL,))
                generic.assert_not_called()
                self.assertEqual(result['data']['company'], 'Pineca Group')
                self.assertEqual(result['data']['job_url'], url)
                self.assertEqual(result['data']['source'], 'Greenhouse')
                for field in ('salary_min', 'salary_max', 'currency'):
                    self.assertNotIn(field, result['data'])

    def test_eu_content_maps_labelled_monthly_salary_and_hybrid_model(self):
        payload = dict(job_payload(), id=4988463101, company_name='Pineca Group', location={'name': 'Vilnius, Lithuania'})
        payload['content'] = (Path(settings.BASE_DIR) / 'tests/fixtures/greenhouse_eu_job_content.html').read_text(encoding='utf-8')
        with patch.object(job_import, 'fetch_public_json', return_value=payload):
            data = job_import.import_job_details(EU_URL)['data']
        self.assertEqual(data['location'], 'Vilnius, Lithuania')
        self.assertEqual(data['work_mode'], 'hybrid')
        self.assertEqual(data['salary_min'], '3500.00')
        self.assertEqual(data['salary_max'], '5000.00')
        self.assertEqual(data['currency'], 'EUR')
        self.assertNotIn('employment_type', data)

    def test_detection_rejects_invalid_ids_paths_and_lookalike_hosts(self):
        for url in (
            'https://job-boards.greenhouse.io/drivewealth/jobs/not-a-number',
            'https://job-boards.greenhouse.io/drivewealth/jobs/-1',
            'https://job-boards.greenhouse.io/drivewealth/jobs/0',
            'https://job-boards.greenhouse.io/drivewealth/jobs/5869146003/extra',
            'https://job-boards.greenhouse.io/drivewealth/jobs/?gh_jid=5869146003',
            'https://job-boards.greenhouse.io.evil.example.com/drivewealth/jobs/5869146003',
            'https://job-boards.greenhouse.io/%2e%2e/jobs/5869146003',
            EU_URL.replace('4988463101', 'invalid'),
            EU_URL.replace('job-boards.eu.greenhouse.io', 'job-boards.eu.greenhouse.io.evil.example.com'),
        ):
            with self.subTest(url=url), patch.object(job_import, 'fetch_public_json') as api:
                with patch.object(job_import, 'fetch_public_html', return_value=(FIXTURE, url)) as generic:
                    result = job_import.import_job_details(url)
                api.assert_not_called()
                generic.assert_called_once_with(url)
                self.assertEqual(result['data']['job_url'], url)

    def test_url_credentials_and_schemes_rejected_before_adapter(self):
        for url in (
            'https://user:secret@job-boards.greenhouse.io/drivewealth/jobs/5869146003',
            'ftp://job-boards.greenhouse.io/drivewealth/jobs/5869146003',
        ):
            with self.subTest(url=url), patch.object(job_import, 'fetch_public_json') as api:
                with patch.object(job_import, 'fetch_public_html') as generic:
                    with self.assertRaises(job_import.JobImportError):
                        job_import.import_job_details(url)
                api.assert_not_called()
                generic.assert_not_called()

    def test_missing_fields_stay_missing(self):
        result = self.import_payload({'id': 5869146003, 'title': 'Accountant'})
        self.assertEqual(result['data'], {'job_title': 'Accountant', 'source': 'Greenhouse', 'job_url': GREENHOUSE_URL})
        self.assertIn('remaining fields manually', ' '.join(result['warnings']))

    def test_salary_cents_are_converted_to_currency_units(self):
        payload = job_payload()
        payload['pay_input_ranges'] = [{'min_cents': 14000000, 'max_cents': 15000000, 'currency_type': 'USD'}]
        result = self.import_payload(payload)
        self.assertEqual(result['data']['salary_min'], '140000.00')
        self.assertEqual(result['data']['salary_max'], '150000.00')
        self.assertEqual(result['data']['currency'], 'USD')
        self.assertIn('pay period', ' '.join(result['warnings']))

    def test_structured_eur_monthly_salary_and_precedence(self):
        payload = job_payload()
        payload['pay_input_ranges'] = [{'min_cents': 330000, 'max_cents': 480000, 'currency_type': 'EUR'}]
        payload['content'] = '<p>Salary: EUR 3,500 - 5,000 gross per month</p>'
        data = self.import_payload(payload)['data']
        self.assertEqual(data['salary_min'], '3300.00')
        self.assertEqual(data['salary_max'], '4800.00')
        self.assertEqual(data['currency'], 'EUR')

    def test_explicit_labelled_salary_formats(self):
        for content, minimum, maximum, currency in (
            ('Salary: \u20ac3,300 - \u20ac4,800 gross per month', '3300.00', '4800.00', 'EUR'),
            ('Competitive salary: EUR 3,500 - 5,000 gross per month based on your skills and experience.', '3500.00', '5000.00', 'EUR'),
            ('Pay range: $140,000 - $150,000 USD', '140000.00', '150000.00', 'USD'),
            ('Compensation: USD 120,000\u2013140,000', '120000.00', '140000.00', 'USD'),
            ('Annual salary: \u00a350,000 - \u00a360,000 per year', '50000.00', '60000.00', 'GBP'),
            ('<h4>Salary range</h4><p>EUR 3,300 - 4,800 gross per month</p>', '3300.00', '4800.00', 'EUR'),
        ):
            with self.subTest(content=content):
                payload = job_payload()
                payload['content'] = f'<div>{content}</div>'
                data = self.import_payload(payload)['data']
                self.assertEqual(data['salary_min'], minimum)
                self.assertEqual(data['salary_max'], maximum)
                self.assertEqual(data['currency'], currency)

    def test_labelled_salary_without_reliable_currency_leaves_currency_blank(self):
        for content in ('Salary: 3300 - 4800 per month', 'Pay Range: $140,000 - $150,000'):
            with self.subTest(content=content):
                payload = dict(job_payload(), content=f'<p>{content}</p>')
                data = self.import_payload(payload)['data']
                self.assertIn('salary_min', data)
                self.assertIn('salary_max', data)
                self.assertNotIn('currency', data)

    def test_unlabelled_numbers_and_conflicting_pay_ranges_are_not_salary(self):
        for content in (
            '<p>\u20ac3,300 - \u20ac4,800 gross per month</p>',
            '<h4>Benefits</h4><p>USD 120,000 - 140,000</p>',
            '<p>Our team grew from 3300 to 4800 employees.</p>',
            '<p>Salary: 3300 - 4800 EUR</p><p>Salary: 5000 - 6000 EUR</p>',
            '<p>Salary: 3300 - 4800 EUR per month</p><p>Salary: 3300 - 4800 EUR per year</p>',
            '<p>Salary: \u20ac3300 - \u00a34800</p>',
            '<p>Salary: $3300 - $4800 EUR</p>',
            '<p>Salary: EUR 3,30 - 4800</p>',
        ):
            with self.subTest(content=content):
                data = self.import_payload(dict(job_payload(), content=content))['data']
                for field in ('salary_min', 'salary_max', 'currency'):
                    self.assertNotIn(field, data)

    def test_salary_absent_does_not_scrape_description_or_invent_amounts(self):
        payload = job_payload()
        payload['content'] = 'Salary $95,000 - $120,000 per year. Remote work.'
        result = self.import_payload(payload)
        for field in ('salary_min', 'salary_max', 'currency', 'work_mode', 'notes', 'content'):
            self.assertNotIn(field, result['data'])

    def test_single_salary_bound_is_preserved_without_inventing_other_bound(self):
        payload = job_payload()
        payload['pay_input_ranges'] = [{'max_cents': 12000000, 'currency_type': 'USD'}]
        data = self.import_payload(payload)['data']
        self.assertEqual(data['salary_max'], '120000.00')
        self.assertNotIn('salary_min', data)

    def test_invalid_salary_is_omitted(self):
        for salary in (
            {'min_cents': 500000, 'max_cents': 300000},
            {'min_cents': -1, 'max_cents': True},
            {'min_cents': '9500000', 'max_cents': 9999999999999},
        ):
            with self.subTest(salary=salary):
                payload = job_payload()
                payload['pay_input_ranges'] = [dict(salary, currency_type='USD')]
                data = self.import_payload(payload)['data']
                self.assertNotIn('salary_min', data)
                self.assertNotIn('salary_max', data)
                self.assertNotIn('currency', data)

    def test_multiple_salary_ranges_are_not_combined(self):
        payload = job_payload()
        payload['pay_input_ranges'] = [
            {'min_cents': 5000000, 'max_cents': 7500000, 'currency_type': 'USD'},
            {'min_cents': 6000000, 'max_cents': 8500000, 'currency_type': 'EUR'},
        ]
        result = self.import_payload(payload)
        self.assertNotIn('salary_min', result['data'])
        self.assertNotIn('currency', result['data'])
        self.assertIn('multiple salary ranges', ' '.join(result['warnings']))

    def test_drivewealth_explicit_location_mode_and_labelled_pay_range(self):
        payload = job_payload()
        payload['content'] = (Path(settings.BASE_DIR) / 'tests/fixtures/greenhouse_job_content.html').read_text(encoding='utf-8')
        data = self.import_payload(payload)['data']
        self.assertEqual(data['location'], 'New York, NY')
        self.assertEqual(data['work_mode'], 'hybrid')
        self.assertEqual(data['salary_min'], '140000.00')
        self.assertEqual(data['salary_max'], '150000.00')
        self.assertEqual(data['currency'], 'USD')

    def test_currency_absent_stays_absent_even_when_salary_is_available(self):
        payload = job_payload()
        payload['pay_input_ranges'] = [{'min_cents': 14000000, 'max_cents': 15000000}]
        data = self.import_payload(payload)['data']
        self.assertEqual(data['salary_min'], '140000.00')
        self.assertNotIn('currency', data)

    def test_only_unambiguous_general_or_exact_location_pay_range_is_selected(self):
        for title in ('General Pay Range', 'New York, NY Salary Range'):
            with self.subTest(title=title):
                payload = job_payload()
                payload['location']['name'] = 'New York, NY'
                payload['pay_input_ranges'] = [
                    {'title': 'Berlin Salary Range', 'min_cents': 9000000, 'max_cents': 10000000, 'currency_type': 'EUR'},
                    {'title': title, 'min_cents': 14000000, 'max_cents': 15000000, 'currency_type': 'USD'},
                ]
                data = self.import_payload(payload)['data']
                self.assertEqual(data['salary_min'], '140000.00')
                self.assertEqual(data['salary_max'], '150000.00')
                self.assertEqual(data['currency'], 'USD')

    def test_conflicting_applicable_ranges_do_not_use_content_fallback(self):
        payload = job_payload()
        payload['content'] = '<p>Pay Range: $140,000 - $150,000 USD</p>'
        payload['pay_input_ranges'] = [
            {'title': 'General Pay Range', 'min_cents': 9000000, 'max_cents': 10000000, 'currency_type': 'USD'},
            {'title': 'Global Pay Range', 'min_cents': 14000000, 'max_cents': 15000000, 'currency_type': 'USD'},
        ]
        data = self.import_payload(payload)['data']
        self.assertNotIn('salary_min', data)
        self.assertNotIn('currency', data)

    def test_explicit_work_mode_content(self):
        for content, mode in (
            ('This is a hybrid role.', 'hybrid'),
            ('Remote position', 'remote'),
            ('On-site role', 'onsite'),
            ('Work mode: Onsite', 'onsite'),
            ('This role is remote.', 'remote'),
            ('This is a fully remote position.', 'remote'),
            ('Workplace type: Hybrid', 'hybrid'),
            ('Hybrid', 'hybrid'),
            ('Hybrid working model', 'hybrid'),
            ('Hybrid work model: three office days per week.', 'hybrid'),
            ('Hybrid working model: work from the office Monday to Wednesday, and enjoy the flexibility to work from home the rest of the week.', 'hybrid'),
            ('Remote', 'remote'),
            ('Fully remote', 'remote'),
            ('Remote, EU', 'remote'),
            ('Remote - EU', 'remote'),
            ('Remote, Ireland', 'remote'),
            ('Remote within Europe', 'remote'),
            ('On-site', 'onsite'),
            ('Onsite', 'onsite'),
            ('On site', 'onsite'),
            ('Office-based', 'onsite'),
            ('Office based', 'onsite'),
            ('This role is based on site.', 'onsite'),
            ('On-site in Vilnius', 'onsite'),
        ):
            with self.subTest(content=content):
                payload = job_payload()
                payload['content'] = f'<p>{content}</p>'
                self.assertEqual(self.import_payload(payload)['data']['work_mode'], mode)

    def test_ambiguous_or_negated_work_mode_is_not_imported(self):
        for content in (
            'We have an office and occasional remote work.',
            'Flexible working with remote and hybrid options.',
            'This is not a hybrid role.',
            'Remote work may be available later.',
            'This role is remote if needed.',
            'This role is hybrid or remote.',
            'This is a hybrid role if available.',
            'Other teams are hiring remote positions.',
            'Remote collaboration with an international team.',
            'We offer a flexible workplace and an office available for meetings.',
            'Occasional work from home.',
            'Hybrid working model may be available.',
            'This role is not based on site.',
            '<p>Hybrid role</p><p>Remote position</p>',
            '<script>This is a hybrid role.</script><style>Remote position</style>',
        ):
            with self.subTest(content=content):
                payload = job_payload()
                payload['content'] = content
                self.assertNotIn('work_mode', self.import_payload(payload)['data'])

    def test_precise_primary_location_is_not_overwritten_or_guessed(self):
        payload = job_payload()
        payload['location']['name'] = 'Berlin, Germany'
        payload['content'] = '<p>New York, NY - Hybrid</p>'
        self.assertEqual(self.import_payload(payload)['data']['location'], 'Berlin, Germany')
        payload['location']['name'] = 'Office - NYC'
        payload['content'] = '<p>Flexible office working.</p>'
        self.assertEqual(self.import_payload(payload)['data']['location'], 'Office - NYC')

    def test_primary_location_separates_geography_and_work_mode(self):
        for primary, location, mode in (
            ('Vilnius, Lithuania - Hybrid', 'Vilnius, Lithuania', 'hybrid'),
            ('New York, NY - Hybrid', 'New York, NY', 'hybrid'),
            ('Remote, EU', 'EU', 'remote'),
            ('Remote - EU', 'EU', 'remote'),
            ('Remote, Ireland', 'Ireland', 'remote'),
            ('Remote within Europe', 'Europe', 'remote'),
            ('On-site in Vilnius', 'Vilnius', 'onsite'),
        ):
            with self.subTest(primary=primary):
                payload = dict(job_payload(), location={'name': primary})
                data = self.import_payload(payload)['data']
                self.assertEqual(data['location'], location)
                self.assertEqual(data['work_mode'], mode)

    def test_content_location_refines_generic_but_preserves_precise_api_location(self):
        for content, expected, mode in (
            ('Vilnius, Lithuania - Hybrid', 'Vilnius, Lithuania', 'hybrid'),
            ('Remote, EU', 'EU', 'remote'),
            ('Remote, Ireland', 'Ireland', 'remote'),
        ):
            with self.subTest(content=content):
                payload = dict(job_payload(), location={'name': 'Office'}, content=f'<p>{content}</p>')
                data = self.import_payload(payload)['data']
                self.assertEqual(data['location'], expected)
                self.assertEqual(data['work_mode'], mode)
                payload['location']['name'] = 'Vilnius, Lithuania'
                self.assertEqual(self.import_payload(payload)['data']['location'], 'Vilnius, Lithuania')

    def test_conflicting_content_locations_are_not_selected(self):
        payload = job_payload()
        payload['content'] = '<p>New York, NY - Hybrid</p><p>Berlin, Germany - Remote</p>'
        data = self.import_payload(payload)['data']
        self.assertEqual(data['location'], 'Office - NYC')
        self.assertNotIn('work_mode', data)

    def test_explicit_content_employment_and_metadata_precedence(self):
        payload = job_payload()
        payload['content'] = '<p>This is a full-time role.</p><p>This is a hybrid role.</p>'
        data = self.import_payload(payload)['data']
        self.assertEqual(data['employment_type'], 'full_time')
        payload['metadata'] = [
            {'name': 'Employment type', 'value': 'Contract'},
            {'name': 'Work mode', 'value': 'On-site'},
        ]
        data = self.import_payload(payload)['data']
        self.assertEqual(data['employment_type'], 'contract')
        self.assertEqual(data['work_mode'], 'onsite')
        payload['metadata'] = None
        payload['content'] = '<p>Applicants must be authorized to work on a full-time basis.</p>'
        self.assertNotIn('employment_type', self.import_payload(payload)['data'])

    def test_content_pay_range_requires_label_and_unique_valid_range(self):
        for content in (
            '<p>Revenue was $140,000 - $150,000 USD.</p>',
            '<p>Pay Range: $140,000 - $150,000 USD</p><p>Pay Range: 90000 - 100000 EUR</p>',
            '<p>Pay Range: $150,000 - $140,000 USD</p>',
            '<script>Pay Range: $140,000 - $150,000 USD</script>',
        ):
            with self.subTest(content=content):
                payload = job_payload()
                payload['content'] = content
                data = self.import_payload(payload)['data']
                self.assertNotIn('salary_min', data)
                self.assertNotIn('salary_max', data)
                self.assertNotIn('currency', data)

    def test_only_explicit_employment_and_work_mode_metadata_is_mapped(self):
        payload = job_payload()
        payload['metadata'] = [
            {'name': 'Employment type', 'value': 'Full-time'},
            {'name': 'Workplace type', 'value': 'Hybrid'},
            {'name': 'Description', 'value': 'Remote'},
        ]
        data = self.import_payload(payload)['data']
        self.assertEqual(data['employment_type'], 'full_time')
        self.assertEqual(data['work_mode'], 'hybrid')
        self.assertEqual(data['location'], 'Office - NYC')

    def test_ambiguous_or_unknown_metadata_is_not_guessed(self):
        for metadata in (
            [{'name': 'Employment type', 'value': ['Full-time', 'Part-time']}],
            [{'name': 'Work mode', 'value': 'Flexible'}],
            [{'name': 'Department', 'value': 'Remote'}],
            [None, 'Remote', {'name': [], 'value': 'Full-time'}],
        ):
            with self.subTest(metadata=metadata):
                payload = job_payload()
                payload['metadata'] = metadata
                data = self.import_payload(payload)['data']
                self.assertNotIn('employment_type', data)
                self.assertNotIn('work_mode', data)

    def test_adapter_failure_uses_generic_with_original_url_and_deadline(self):
        with patch.object(job_import.time, 'monotonic', return_value=10):
            with patch.object(job_import, 'fetch_public_json', side_effect=job_import.JobImportError()) as api:
                with patch.object(job_import, 'fetch_public_html', return_value=(FIXTURE, GREENHOUSE_URL)) as generic:
                    result = job_import.import_job_details(GREENHOUSE_URL)
        api.assert_called_once_with(API_URL, deadline=14)
        generic.assert_called_once_with(GREENHOUSE_URL, deadline=18)
        self.assertEqual(result['data']['job_url'], GREENHOUSE_URL)
        self.assertEqual(result['data']['source'], 'Greenhouse')

    def test_unknown_eu_board_falls_back_with_original_url_and_deadline(self):
        url = EU_URL.replace('pinecagroup', 'unknown-board')
        api_url = EU_API_URL.replace('pinecagroup', 'unknown-board')
        with patch.object(job_import.time, 'monotonic', return_value=10):
            with patch.object(job_import, 'fetch_public_json', side_effect=job_import.JobImportError()) as api:
                with patch.object(job_import, 'fetch_public_html', return_value=(FIXTURE, url)) as generic:
                    data = job_import.import_job_details(url)['data']
        api.assert_called_once_with(api_url, deadline=14)
        generic.assert_called_once_with(url, deadline=18)
        self.assertEqual(data['job_url'], url)
        self.assertEqual(data['source'], 'Greenhouse')

    def test_bad_job_response_falls_back_without_guessing(self):
        for payload in (None, [], {}, {'id': True}, {'id': 123}, {'id': 5869146003}):
            with self.subTest(payload=payload), patch.object(job_import, 'fetch_public_json', return_value=payload):
                with patch.object(job_import, 'fetch_public_html', return_value=(FIXTURE, GREENHOUSE_URL)) as generic:
                    self.assertEqual(job_import.import_job_details(GREENHOUSE_URL)['data']['job_url'], GREENHOUSE_URL)
                generic.assert_called_once()


class GreenhouseNetworkTests(SimpleTestCase):
    def fetch_response(self, response):
        with patch.object(job_import, 'resolve_public_host', return_value=PUBLIC_ADDRESS):
            with patch.object(job_import, 'PublicConnection') as connection:
                connection.return_value.getresponse.return_value = response
                result = job_import.fetch_public_json(API_URL)
                headers = connection.return_value.request.call_args.kwargs['headers']
                self.assertEqual(headers['Accept'], 'application/json')
                self.assertNotIn('Authorization', headers)
                self.assertNotIn('Cookie', headers)
                self.assertEqual(connection.call_args.args[2], PUBLIC_ADDRESS)
                return result

    def test_valid_json_uses_existing_pinned_connection(self):
        response = response_mock(json.dumps(job_payload()).encode(), headers={'Content-Type': 'application/json; charset=utf-8'})
        self.assertEqual(self.fetch_response(response), job_payload())

    def test_eu_adapter_uses_existing_validated_pinned_connection(self):
        payload = dict(job_payload(), id=4988463101)
        with patch.object(job_import.time, 'monotonic', return_value=10), patch.object(
            job_import, 'resolve_public_host', return_value=PUBLIC_ADDRESS,
        ) as resolve:
            with patch.object(job_import, 'PublicConnection') as connection:
                connection.return_value.getresponse.return_value = response_mock(
                    json.dumps(payload).encode(), headers={'Content-Type': 'application/json'},
                )
                data = job_import.import_job_details(EU_URL)['data']
        self.assertEqual(data['job_url'], EU_URL)
        self.assertEqual(resolve.call_args.args, ('boards-api.greenhouse.io', 443, 14))
        self.assertEqual(connection.call_args.args[2], PUBLIC_ADDRESS)
        self.assertEqual(connection.call_args.args[4], 14)
        self.assertEqual(connection.return_value.request.call_args.args[:2], (
            'GET', '/v1/boards/pinecagroup/jobs/4988463101?pay_transparency=true',
        ))

    def test_json_fetch_rejects_private_redirects_bad_types_size_timeout_and_malformed_json(self):
        for response in (
            response_mock(status=302, headers={'Location': 'http://169.254.169.254/latest/meta-data'}),
            response_mock(b'{}', headers={'Content-Type': 'text/html'}),
            response_mock(b'{broken', headers={'Content-Type': 'application/json'}),
            response_mock(b'{}', headers={'Content-Type': 'application/json', 'Content-Encoding': 'gzip'}),
            response_mock(headers={'Content-Type': 'application/json', 'Content-Length': str(job_import.MAX_RESPONSE_BYTES + 1)}),
            response_mock(b'x' * (job_import.MAX_RESPONSE_BYTES + 1), headers={'Content-Type': 'application/json'}),
        ):
            with self.subTest(response=response), self.assertRaises(job_import.JobImportError):
                self.fetch_response(response)
        response = response_mock(headers={'Content-Type': 'application/json'})
        response.read1.side_effect = TimeoutError('private details')
        with self.assertRaisesMessage(job_import.JobImportError, job_import.MANUAL_MESSAGE):
            self.fetch_response(response)

    def test_api_and_unknown_board_http_failures_fall_back_safely(self):
        for status in (404, 403, 429, 500):
            with self.subTest(status=status), patch.object(job_import, 'resolve_public_host', return_value=PUBLIC_ADDRESS):
                with patch.object(job_import, 'PublicConnection') as connection:
                    connection.return_value.getresponse.side_effect = [response_mock(status=status), response_mock(FIXTURE.encode())]
                    url = GREENHOUSE_URL.replace('drivewealth', 'unknown-board')
                    data = job_import.import_job_details(url)['data']
                    self.assertEqual(data['job_url'], url)
                    self.assertEqual(connection.call_count, 2)

    def test_generic_fetch_still_rejects_json(self):
        with patch.object(job_import, 'resolve_public_host', return_value=PUBLIC_ADDRESS):
            with patch.object(job_import, 'PublicConnection') as connection:
                connection.return_value.getresponse.return_value = response_mock(b'{}', headers={'Content-Type': 'application/json'})
                with self.assertRaises(job_import.JobImportError):
                    job_import.fetch_public_html(GREENHOUSE_URL)

    def test_api_dns_must_be_public_even_for_known_provider(self):
        private = (PUBLIC_ADDRESS[0], PUBLIC_ADDRESS[1], 6, '', ('10.0.0.1', 443))
        with patch.object(job_import.socket, 'getaddrinfo', return_value=[PUBLIC_ADDRESS, private]):
            with patch.object(job_import, 'PublicConnection') as connection:
                with self.assertRaises(job_import.JobImportError):
                    job_import.fetch_public_json(API_URL)
                connection.assert_not_called()

    def test_api_excessive_redirects_are_rejected(self):
        with patch.object(job_import, 'resolve_public_host', return_value=PUBLIC_ADDRESS):
            with patch.object(job_import, 'PublicConnection') as connection:
                connection.return_value.getresponse.return_value = response_mock(status=302, headers={'Location': '/again'})
                with self.assertRaises(job_import.JobImportError):
                    job_import.fetch_public_json(API_URL)
                self.assertEqual(connection.call_count, job_import.MAX_REDIRECTS + 1)


class GreenhouseEndpointTests(TestCase):
    def test_greenhouse_import_only_returns_review_data_without_saving(self):
        user = get_user_model().objects.create_user(username='greenhouse-reviewer')
        self.client.force_login(user)
        with patch.object(job_import, 'fetch_public_json', return_value=job_payload()):
            response = self.client.post(reverse('application_import'), {'url': GREENHOUSE_URL})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertEqual(response.json()['data']['company'], 'DriveWealth')
        self.assertEqual(response.json()['data']['job_url'], GREENHOUSE_URL)
        self.assertEqual(JobApplication.objects.count(), 0)
        self.assertEqual(ApplicationDocument.objects.count(), 0)
        self.assertNotIn('pay_input_ranges', response.json()['data'])

    def test_failed_api_and_generic_fetch_keep_friendly_error(self):
        user = get_user_model().objects.create_user(username='greenhouse-failure-reviewer')
        self.client.force_login(user)
        with patch.object(job_import, 'fetch_public_json', side_effect=job_import.JobImportError()):
            with patch.object(job_import, 'fetch_public_html', side_effect=job_import.JobImportError()):
                response = self.client.post(reverse('application_import'), {'url': GREENHOUSE_URL})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['message'], job_import.MANUAL_MESSAGE)
