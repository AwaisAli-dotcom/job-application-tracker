"""Map public Greenhouse job-board data without scraping job descriptions."""

import re
from decimal import Decimal
from urllib.parse import urlsplit


API_ROOT = 'https://boards-api.greenhouse.io/v1/boards'
BOARD_HOSTS = {'job-boards.greenhouse.io', 'boards.greenhouse.io'}


def job_reference(url):
    parts = urlsplit(url)
    if parts.hostname not in BOARD_HOSTS:
        return None
    match = re.fullmatch(r'/([A-Za-z0-9_-]{1,100})/jobs/([1-9][0-9]{0,19})/?', parts.path)
    return (match[1], match[2]) if match else None


def cents_amount(value):
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 999999999999:
        return Decimal(value) / 100
    return None


def fetch_job_posting(reference, fetch_json, deadline):
    board, job_id = reference
    payload = fetch_json(f'{API_ROOT}/{board}/jobs/{job_id}?pay_transparency=true', deadline=deadline)
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get('id'), int)
        or isinstance(payload['id'], bool)
        or str(payload['id']) != job_id
    ):
        raise ValueError('Unexpected job-board response')

    location = payload.get('location')
    posting = {
        'title': payload.get('title'),
        'hiringOrganization': {'name': payload.get('company_name')},
        'jobLocation': location.get('name') if isinstance(location, dict) else None,
    }
    warnings = []
    metadata = payload.get('metadata')
    if isinstance(metadata, list):
        employment_types = []
        work_modes = []
        for field in metadata:
            if not isinstance(field, dict) or not isinstance(field.get('name'), str):
                continue
            name = field['name'].strip().lower()
            value = field.get('value')
            values = value if isinstance(value, list) else [value]
            if name in {'employment type', 'employment_type'}:
                employment_types.extend(values)
            elif name in {'work mode', 'work_mode', 'workplace type', 'workplace_type'}:
                work_modes.extend(values)
        posting['employmentType'] = employment_types
        posting['jobLocationType'] = work_modes

    ranges = payload.get('pay_input_ranges')
    if isinstance(ranges, list) and len(ranges) == 1 and isinstance(ranges[0], dict):
        salary = ranges[0]
        posting['baseSalary'] = {
            'currency': salary.get('currency_type'),
            'value': {
                'minValue': cents_amount(salary.get('min_cents')),
                'maxValue': cents_amount(salary.get('max_cents')),
            },
        }
        warnings.append('Review the published salary range and its pay period before saving.')
    elif isinstance(ranges, list) and len(ranges) > 1:
        warnings.append('This job lists multiple salary ranges. Enter the appropriate range manually.')
    return posting, warnings
