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
        ('description', 'descriptionPlain'), ('descriptionBody', 'descriptionBodyPlain'),
        ('additional', 'additionalPlain'),
        ('salaryDescription', 'salaryDescriptionPlain'),
    ):
        html = payload.get(html_field)
        plain = payload.get(plain_field)
        if html_field == 'salaryDescription' and (html or plain):
            lines.append('Compensation')
        if isinstance(plain, str) and plain.strip() and len(plain) <= 1024 * 1024:
            lines.extend(' '.join(line.split()) for line in plain.splitlines() if line.strip())
        elif isinstance(html, str) and html:
            lines.extend(greenhouse.content_lines(html))
    lists = payload.get('lists')
    if isinstance(lists, list):
        for section in lists:
            if isinstance(section, dict):
                heading = section.get('text')
                if isinstance(heading, str):
                    lines.append(' '.join(heading.split()))
                lines.extend(greenhouse.content_lines(section.get('content')))
    return lines


def role_work_modes(lines):
    values = set()
    perks = False
    for line in lines:
        if re.fullmatch(r'(?:our |employee |company )?(?:benefits(?: and perks)?|perks|extra sweeteners|what we offer|compensation (?:and|&) benefits)\s*:?', line, re.I):
            perks = True
        elif re.fullmatch(r'(?:about (?:the )?(?:role|position)|job details|responsibilities|workplace)\s*:?', line, re.I):
            perks = False
        # Role-specific statements remain valid even inside a benefits section.
        values.update(greenhouse.explicit_role_values(
            [line], greenhouse.WORK_MODE_PATTERN, r'(?:workplace(?: type)?|work mode|work arrangement)',
        ))
        expressions = [
            rf'^(?:role|position|job) is (?:fully )?{greenhouse.WORK_MODE_PATTERN}(?=[.,;]|$)',
        ]
        if not perks:
            expressions.append(rf'^(?:fully )?{greenhouse.WORK_MODE_PATTERN}[.]?$')
        for expression in expressions:
            match = re.search(expression, line, re.I)
            if match:
                values.add(match[1])
    return {greenhouse.work_mode_value(value) for value in values}


def content_salary(lines):
    number = r'(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{1,3}(?: [0-9]{3})+|[0-9]+)(?:\.[0-9]{1,2})?'
    currency = r'(?:[$\u20ac\u00a3]|(?!per\b|net\b)[A-Za-z]{3}\b)'
    label = r'(?:competitive\s+)?(?:(?:base|annual|monthly)\s+)?(?:salary|pay|compensation)(?:\s+range)?\b'
    range_pattern = (
        rf'(?P<first>{currency})?\s*(?P<minimum>{number})\s*(?P<second>{currency})?\s*[-\u2013\u2014]\s*'
        rf'(?P<third>{currency})?\s*(?P<maximum>{number})\s*(?P<fourth>{currency})?'
        r'(?:\s*(?P<before>gross|net|base))?'
        r'(?:\s*(?:/\s*|per\s+|a\s+)?(?P<period>monthly|month|yearly|year|annually|annual|annum|weekly|week|daily|day|hourly|hour))?'
        r'(?:\s*(?P<after>gross|net|base))?'
        r'(?:\.\s+.*|\s*\+\s*bonus\b.*|\s+(?:based on|depending on|commensurate with)\b.*)?[.]?'
    )
    normalized = []
    salary_heading = False
    excluded_heading = False
    for line in lines:
        labelled = re.match(rf'^{label}\s*[:\-]?\s*', line, re.I)
        if labelled and not line[labelled.end():]:
            salary_heading = True
            excluded_heading = False
            continue
        if re.fullmatch(r'(?:our |employee |company )?(?:benefits(?: and perks)?|perks|extra sweeteners|compensation (?:and|&) benefits|(?:annual )?learning(?: (?:and|&) development)? budget|revenue|customer counts|products sold)\s*:?', line, re.I):
            excluded_heading = True
        positions = {labelled.end()} if labelled else set()
        for match in re.finditer(rf'\b{label}\s*:\s*', line, re.I):
            positions.add(match.end())
            if len(positions) > 100:
                return None
        explicit = bool(positions) or salary_heading
        candidates = [line[position:position + 4096] for position in sorted(positions)] if positions else [line[:4096]]
        for text in candidates:
            match = re.fullmatch(range_pattern, text, re.I)
            if not match:
                continue
            if not explicit and (excluded_heading or not match['period'] or not (match['before'] or match['after'])):
                continue
            minimum = match['minimum'].replace(',', '').replace(' ', '')
            maximum = match['maximum'].replace(',', '').replace(' ', '')
            amounts = f"{match['first'] or ''} {minimum} {match['second'] or ''} - {match['third'] or ''} {maximum} {match['fourth'] or ''}"
            period = match['period'] or ''
            period = {'monthly': 'month', 'yearly': 'year', 'annual': 'year', 'annually': 'year', 'annum': 'year', 'weekly': 'week', 'daily': 'day', 'hourly': 'hour'}.get(period.lower(), period.lower())
            normalized.append(f'Salary range: {amounts}' + (f' per {period}' if period else ''))
        salary_heading = False
    return greenhouse.content_salary(normalized)


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
    modes = {'remote': 'REMOTE', 'hybrid': 'HYBRID', 'on-site': 'ON_SITE', 'onsite': 'ON_SITE', 'on site': 'ON_SITE'}
    if workplace in modes:
        work_modes = [modes[workplace]]
    elif workplace in {'', 'unspecified'}:
        work_modes = list(location_modes | role_work_modes(lines))
    else:
        work_modes = []
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
        salary = content_salary(lines)
        if salary:
            posting['baseSalary'] = salary
            warnings.append('Review the explicitly labelled pay range and its pay period before saving.')
    else:
        warnings.append('The salary range could not be imported. Enter it manually if needed.')
    return posting, warnings
