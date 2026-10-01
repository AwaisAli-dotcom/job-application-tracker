"""Map public Greenhouse data with conservative, explicitly labelled content fallbacks."""

import re
from decimal import Decimal
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit


API_ROOT = 'https://boards-api.greenhouse.io/v1/boards'
BOARD_HOSTS = {'job-boards.greenhouse.io', 'boards.greenhouse.io'}
WORK_MODE_PATTERN = r'(hybrid|remote|on[- ]?site)'
EMPLOYMENT_PATTERN = r'(full[- ]time|part[- ]time|contract|temporary|internship)'


class ContentLines(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines = []
        self.current = []
        self.hidden = 0

    def flush(self):
        line = ' '.join(''.join(self.current).split())
        if line:
            self.lines.append(line)
        self.current = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.hidden += 1
        elif not self.hidden and tag in {'p', 'li', 'div', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
            self.flush()

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in {'p', 'li', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
            self.flush()

    def handle_data(self, data):
        if not self.hidden:
            self.current.append(data)


def content_lines(content):
    if not isinstance(content, str) or len(content) > 1024 * 1024:
        return []
    parser = ContentLines()
    parser.feed(unescape(content))
    parser.flush()
    return parser.lines


def explicit_role_values(lines, pattern, label):
    values = set()
    for line in lines:
        for expression in (
            rf'^{label}\s*:\s*{pattern}[.]?$',
            rf'^{pattern}\s+(?:role|position|job)[.]?$',
            rf'\bthis is (?:a|an) (?:fully )?{pattern}\s+(?:role|position|job)(?=[.,;]|$)',
            rf'\b(?:this|the) (?:role|position|job) (?:is|will be) (?:fully )?{pattern}(?=[.,;]|$)',
        ):
            match = re.search(expression, line, re.I)
            if match:
                values.add(match[1].upper().replace('-', '_').replace(' ', '_'))
    return values


def content_location(lines):
    locations = set()
    for line in lines:
        # Only standalone locations or explicit job-location statements qualify.
        match = re.fullmatch(
            rf'(?:(?:job location|work location|location|locations|this role is open to candidates in the following locations)\s*:\s*)?'
            rf'([\w .\'()-]+, [\w .\'()-]+)\s+[-\u2013\u2014|]\s+{WORK_MODE_PATTERN}[.]?',
            line, re.I,
        )
        if match:
            locations.add((match[1].strip(), match[2].upper().replace('-', '_').replace(' ', '_')))
    return next(iter(locations)) if len(locations) == 1 else (None, None)


def content_salary(lines):
    number = r'([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)'
    ranges = set()
    for line in lines:
        match = re.fullmatch(
            rf'(?:pay|salary|base salary) range\s*:\s*[$\u20ac\u00a3]?{number}\s*[-\u2013\u2014]\s*'
            rf'[$\u20ac\u00a3]?{number}\s+([A-Za-z]{{3}})(?:\s+(?:per|/)\s*(?:year|month|week|day|hour))?[.]?',
            line, re.I,
        )
        if match:
            ranges.add((match[1].replace(',', ''), match[2].replace(',', ''), match[3].upper()))
    if len(ranges) == 1:
        minimum, maximum, currency = ranges.pop()
        return {'currency': currency, 'value': {'minValue': minimum, 'maxValue': maximum}}
    return None


def select_pay_range(ranges, location):
    if len(ranges) == 1:
        return ranges[0] if isinstance(ranges[0], dict) else None
    applicable = []
    general = []
    for salary in ranges:
        if not isinstance(salary, dict) or not isinstance(salary.get('title'), str):
            continue
        title = ' '.join(salary['title'].split()).lower()
        if re.fullmatch(r'(?:general|global|all locations)(?: (?:pay|salary) range)?', title):
            general.append(salary)
        elif isinstance(location, str) and re.sub(r' (?:pay|salary) range$', '', title) == location.strip().lower():
            applicable.append(salary)
    if len(applicable) == 1:
        return applicable[0]
    return general[0] if not applicable and len(general) == 1 else None


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

    lines = content_lines(payload.get('content'))
    precise_location, location_mode = content_location(lines)
    primary_location = posting['jobLocation']
    if precise_location and (
        not primary_location or (isinstance(primary_location, str) and re.fullmatch(
            r'office(?:\s*[-:]\s*.+)?|remote|hybrid|on[- ]?site', primary_location.strip(), re.I,
        ))
    ):
        posting['jobLocation'] = precise_location
    explicit_modes = explicit_role_values(lines, WORK_MODE_PATTERN, r'(?:work mode|workplace type|work arrangement)')
    if location_mode:
        explicit_modes.add(location_mode)
    metadata_modes = posting.get('jobLocationType', [])
    if not any(isinstance(value, str) and value.strip().upper().replace('-', '_').replace(' ', '_')
               in {'HYBRID', 'REMOTE', 'TELECOMMUTE', 'ON_SITE', 'ONSITE'} for value in metadata_modes):
        posting['jobLocationType'] = list(explicit_modes)
    metadata_types = posting.get('employmentType', [])
    if not any(isinstance(value, str) and value.strip().upper().replace('-', '_').replace(' ', '_')
               in {'FULL_TIME', 'PART_TIME', 'CONTRACT', 'CONTRACTOR', 'TEMPORARY', 'INTERN', 'INTERNSHIP'} for value in metadata_types):
        posting['employmentType'] = list(explicit_role_values(lines, EMPLOYMENT_PATTERN, 'employment type'))

    ranges = payload.get('pay_input_ranges')
    salary = select_pay_range(ranges, posting['jobLocation']) if isinstance(ranges, list) else None
    if salary is not None:
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
    elif ranges in (None, []):
        salary = content_salary(lines)
        if salary:
            posting['baseSalary'] = salary
            warnings.append('Review the explicitly labelled pay range and its pay period before saving.')
    return posting, warnings
