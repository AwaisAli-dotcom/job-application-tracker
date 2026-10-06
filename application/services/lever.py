"""Map published Lever postings without guessing company names or compensation."""

import re
from urllib.parse import urlsplit

from . import greenhouse


API_ROOTS = {
    'jobs.lever.co': 'https://api.lever.co/v0/postings',
    'jobs.eu.lever.co': 'https://api.eu.lever.co/v0/postings',
}
POSTING_ID = r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'


def job_reference(url):
    parts = urlsplit(url)
    root = API_ROOTS.get(parts.hostname)
    match = re.fullmatch(rf'/([A-Za-z0-9][A-Za-z0-9_-]{{0,99}})/({POSTING_ID})/?', parts.path)
    if not root or not match or int(match[2].replace('-', ''), 16) == 0:
        return None
    return root, match[1], match[2].lower()


def company_from_titles(titles, job_title):
    companies = set()
    for title in titles:
        for separator in (' - ', ' \u2013 ', ' \u2014 '):
            match = re.fullmatch(rf'(.+){re.escape(separator)}{re.escape(job_title)}', title, re.I)
            if match:
                company = match[1].strip()
                if company:
                    companies.add(company)
    return next(iter(companies)) if len(companies) == 1 else ''


def posting_lines(payload):
    lines = []
    for html_field, plain_field in (
        ('description', 'descriptionPlain'), ('additional', 'additionalPlain'),
        ('salaryDescription', 'salaryDescriptionPlain'),
    ):
        html = payload.get(html_field)
        plain = payload.get(plain_field)
        if isinstance(html, str) and html:
            lines.extend(greenhouse.content_lines(html))
        elif isinstance(plain, str) and len(plain) <= 1024 * 1024:
            lines.extend(' '.join(line.split()) for line in plain.splitlines() if line.strip())
    lists = payload.get('lists')
    if isinstance(lists, list):
        for section in lists:
            if isinstance(section, dict):
                heading = section.get('text')
                if isinstance(heading, str):
                    lines.append(' '.join(heading.split()))
                lines.extend(greenhouse.content_lines(section.get('content')))
    return lines


def fetch_job_posting(reference, fetch_json, deadline):
    root, site, posting_id = reference
    payload = fetch_json(f'{root}/{site}/{posting_id}?mode=json', deadline=deadline)
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get('id'), str)
        or payload['id'].lower() != posting_id
    ):
        raise ValueError('Unexpected job-board response')

    categories = payload.get('categories')
    categories = categories if isinstance(categories, dict) else {}
    primary = categories.get('location')
    locations = [primary] if isinstance(primary, str) and primary.strip() else categories.get('allLocations', [])
    locations = locations if isinstance(locations, list) else []
    geography = []
    location_modes = set()
    for location in locations:
        if not isinstance(location, str):
            continue
        normalized, mode = greenhouse.content_location([location])
        geography.append(normalized or location)
        if mode:
            location_modes.add(mode)
        location_modes.update(greenhouse.explicit_work_modes([location]))

    lines = posting_lines(payload)
    workplace = payload.get('workplaceType')
    workplace = workplace.strip().lower() if isinstance(workplace, str) else ''
    modes = {'remote': 'REMOTE', 'hybrid': 'HYBRID', 'on-site': 'ON_SITE'}
    work_modes = [modes[workplace]] if workplace in modes else list(
        location_modes | greenhouse.explicit_work_modes(lines),
    )
    commitment = categories.get('commitment')
    if isinstance(commitment, str):
        commitment = commitment.strip().upper().replace('-', '_').replace(' ', '_')
        commitment = {'FULLTIME': 'FULL_TIME', 'PARTTIME': 'PART_TIME'}.get(commitment, commitment)
    if not commitment:
        commitment = list(greenhouse.explicit_role_values(lines, greenhouse.EMPLOYMENT_PATTERN, 'employment type'))

    posting = {
        'title': payload.get('text'), 'jobLocation': geography,
        'employmentType': commitment, 'jobLocationType': work_modes,
    }
    warnings = []
    salary = payload.get('salaryRange')
    if isinstance(salary, dict) and salary:
        interval = salary.get('interval')
        period = re.fullmatch(r'per-(year|month|week|day|hour)-(?:salary|wage)', interval) if isinstance(interval, str) else None
        posting['baseSalary'] = {
            'currency': salary.get('currency'),
            'value': {'minValue': salary.get('min'), 'maxValue': salary.get('max'), 'unitText': period[1] if period else ''},
        }
        warnings.append('Review the published salary range and its pay period before saving.')
    elif salary in (None, {}):
        salary = greenhouse.content_salary(lines)
        if salary:
            posting['baseSalary'] = salary
            warnings.append('Review the explicitly labelled pay range and its pay period before saving.')
    else:
        warnings.append('The salary range could not be imported. Enter it manually if needed.')
    return posting, warnings
