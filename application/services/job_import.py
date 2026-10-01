"""Read public job pages without storing content or creating applications."""

import http.client
import ipaddress
import json
import queue
import re
import socket
import ssl
import threading
import time
from decimal import Decimal, InvalidOperation
from html import unescape
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit, urlunsplit


MAX_URL_LENGTH = 200
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_REDIRECTS = 3
FETCH_TIMEOUT = 8
DNS_TIMEOUT = 2
MANUAL_MESSAGE = (
    "We couldn't import details from this page automatically. "
    'You can still enter the details manually.'
)
URL_MESSAGE = 'Enter a public job listing URL using http:// or https://.'
PROVIDERS = {
    'linkedin.com': 'LinkedIn',
    'indeed.com': 'Indeed',
    'greenhouse.io': 'Greenhouse',
    'greenhouse.com': 'Greenhouse',
    'lever.co': 'Lever',
    'myworkdayjobs.com': 'Workday',
    'ashbyhq.com': 'Ashby',
    'smartrecruiters.com': 'SmartRecruiters',
}
EMPLOYMENT_TYPES = {
    'FULL_TIME': 'full_time',
    'PART_TIME': 'part_time',
    'CONTRACTOR': 'contract',
    'CONTRACT': 'contract',
    'TEMPORARY': 'temporary',
    'INTERN': 'internship',
    'INTERNSHIP': 'internship',
}
COUNTRIES = {
    'LT': 'Lithuania', 'DE': 'Germany', 'GB': 'United Kingdom',
    'US': 'United States', 'FR': 'France', 'PL': 'Poland',
    'LV': 'Latvia', 'EE': 'Estonia', 'NL': 'Netherlands',
    'CA': 'Canada', 'AU': 'Australia', 'IE': 'Ireland',
}


class JobImportError(Exception):
    def __init__(self, message=MANUAL_MESSAGE):
        super().__init__(message)


def validate_job_url(url):
    if not isinstance(url, str) or not url or len(url) > MAX_URL_LENGTH:
        raise JobImportError(URL_MESSAGE)
    if re.search(r'[\s\\\x00-\x1f\x7f]', url):
        raise JobImportError(URL_MESSAGE)
    try:
        parts = urlsplit(url)
        host = (parts.hostname or '').encode('idna').decode('ascii').lower()
        port = parts.port
    except (ValueError, UnicodeError):
        raise JobImportError(URL_MESSAGE) from None

    if (
        parts.scheme not in {'http', 'https'}
        or not host
        or parts.username is not None
        or parts.password is not None
        or '%' in host
        or host.endswith('.')
        or port not in {None, 80 if parts.scheme == 'http' else 443}
    ):
        raise JobImportError(URL_MESSAGE)

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        labels = host.split('.')
        if (
            len(labels) < 2
            or labels[-1] in {'localhost', 'local', 'internal', 'lan', 'home', 'localdomain', 'test', 'invalid'}
            or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in labels)
        ):
            raise JobImportError(URL_MESSAGE)
    else:
        require_public_ip(address)

    return parts, host, port or (443 if parts.scheme == 'https' else 80)


def require_public_ip(address):
    if (
        not address.is_global
        or address.is_multicast
        or address.is_reserved
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        or str(address) == '168.63.129.16'
        or (address.version == 6 and (
            address.is_site_local or address.ipv4_mapped or address.sixtofour or address.teredo
        ))
    ):
        raise JobImportError(URL_MESSAGE)


def remaining_time(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise JobImportError()
    return remaining


def resolve_public_host(host, port, deadline):
    result = queue.Queue(maxsize=1)

    def resolve():
        try:
            result.put(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
        except OSError:
            result.put(None)

    # Bound DNS waiting independently of the system resolver's own retry policy.
    threading.Thread(target=resolve, daemon=True).start()
    try:
        addresses = result.get(timeout=min(DNS_TIMEOUT, remaining_time(deadline)))
    except queue.Empty:
        raise JobImportError() from None
    if not addresses:
        raise JobImportError()
    for family, _, _, _, sockaddr in addresses:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            raise JobImportError(URL_MESSAGE)
        require_public_ip(ipaddress.ip_address(sockaddr[0]))
    return addresses[0]


class PublicConnection(http.client.HTTPConnection):
    def __init__(self, host, port, address, scheme, deadline):
        super().__init__(host, port, timeout=remaining_time(deadline))
        self.address = address
        self.scheme = scheme
        self.deadline = deadline

    def connect(self):
        family, socktype, protocol, _, sockaddr = self.address
        sock = socket.socket(family, socktype, protocol)
        try:
            sock.settimeout(remaining_time(self.deadline))
            # Connect to the validated numeric address; never resolve the host again.
            sock.connect(sockaddr)
            if self.scheme == 'https':
                sock.settimeout(remaining_time(self.deadline))
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
            self.sock = sock
        except Exception:
            sock.close()
            raise


def fetch_public_html(url):
    deadline = time.monotonic() + FETCH_TIMEOUT
    current_url = url
    for redirect_count in range(MAX_REDIRECTS + 1):
        parts, host, port = validate_job_url(current_url)
        address = resolve_public_host(host, port, deadline)
        connection = PublicConnection(host, port, address, parts.scheme, deadline)
        timer = None
        response = None
        try:
            connection.connect()
            connected_socket = connection.sock

            def expire_connection():
                try:
                    connected_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            # A wall-clock limit also stops slow headers and trickling response bodies.
            timer = threading.Timer(remaining_time(deadline), expire_connection)
            timer.daemon = True
            timer.start()
            path = quote(parts.path or '/', safe="/%:@!$&'()*+,;=-._~")
            if parts.query:
                path += '?' + quote(parts.query, safe="%/?@:!$&'()*+,;=-._~")
            connection.request('GET', path, headers={
                'User-Agent': 'JobApplicationTracker/1.0 (public job details importer)',
                'Accept': 'text/html, application/xhtml+xml',
                'Accept-Encoding': 'identity',
                'Connection': 'close',
            })
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader('Location')
                if not location or redirect_count == MAX_REDIRECTS:
                    raise JobImportError()
                current_url = urljoin(current_url, location)
                continue
            if response.status != 200:
                raise JobImportError()
            content_type = response.getheader('Content-Type', '').split(';')[0].strip().lower()
            if content_type not in {'text/html', 'application/xhtml+xml'}:
                raise JobImportError()
            if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                raise JobImportError()
            length = response.getheader('Content-Length')
            if length is not None and (not length.isdigit() or int(length) > MAX_RESPONSE_BYTES):
                raise JobImportError()
            body = bytearray()
            while True:
                remaining_time(deadline)
                chunk = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise JobImportError()
            remaining_time(deadline)
            charset = response.headers.get_content_charset() or 'utf-8'
            try:
                return body.decode(charset, errors='replace'), current_url
            except LookupError:
                return body.decode('utf-8', errors='replace'), current_url
        except (OSError, http.client.HTTPException, ValueError):
            raise JobImportError() from None
        finally:
            if timer:
                timer.cancel()
            if response:
                response.close()
            connection.close()
    raise JobImportError()


class JobPageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.scripts = []
        self.metadata = {}
        self.title = []
        self.canonical = ''
        self.script = None
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('type', '').lower().split(';')[0].strip() == 'application/ld+json':
            self.script = []
        elif tag == 'meta':
            name = (attrs.get('property') or attrs.get('name') or '').lower()
            self.metadata.setdefault(name, attrs.get('content', ''))
        elif tag == 'title':
            self.in_title = True
        elif tag == 'link' and 'canonical' in attrs.get('rel', '').lower().split():
            self.canonical = attrs.get('href', '')

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)
        elif self.in_title:
            self.title.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.script is not None:
            self.scripts.append(''.join(self.script))
            self.script = None
        elif tag == 'title':
            self.in_title = False


def clean_text(value, limit):
    if not isinstance(value, str) or len(value) > max(limit * 4, 1024):
        return ''
    value = re.sub(r'<[^>]*>', '', unescape(value))
    value = re.sub(r'[\x00-\x1f\x7f]', ' ', value)
    value = ' '.join(value.split())
    return value if len(value) <= limit else ''


def find_job_postings(value, depth=0):
    if depth > 20:
        return
    if isinstance(value, list):
        for item in value:
            yield from find_job_postings(item, depth + 1)
    elif isinstance(value, dict):
        types = value.get('@type', [])
        types = [types] if isinstance(types, str) else types
        if isinstance(types, list) and any(
            isinstance(item, str) and item.rsplit('/', 1)[-1] == 'JobPosting' for item in types
        ):
            yield value
        for key in ('@graph', 'mainEntity', 'itemListElement', 'item'):
            if key in value:
                yield from find_job_postings(value[key], depth + 1)


def country_name(value):
    if isinstance(value, dict):
        value = value.get('name', '')
    value = clean_text(value, 80)
    return COUNTRIES.get(value.upper(), value)


def location_text(value):
    if isinstance(value, str):
        return clean_text(value, 150)
    if not isinstance(value, dict):
        return ''
    address = value.get('address', value)
    if isinstance(address, str):
        return clean_text(address, 150)
    if not isinstance(address, dict):
        return ''
    parts = [
        clean_text(address.get('addressLocality', ''), 100),
        country_name(address.get('addressCountry', '')),
    ]
    if not any(parts):
        parts = [clean_text(value.get('name', ''), 100)]
    return ', '.join(dict.fromkeys(part for part in parts if part))


def as_list(value):
    return value if isinstance(value, list) else [value]


def salary_number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return ''
    if len(str(value)) > 32:
        return ''
    try:
        number = Decimal(str(value))
        if not number.is_finite() or not 0 <= number <= Decimal('9999999999.99'):
            return ''
        if number * 100 != (number * 100).to_integral_value():
            return ''
        return format(number.quantize(Decimal('0.01')), 'f')
    except InvalidOperation:
        return ''


def normalize_job(posting):
    data = {}
    warnings = []
    company = posting.get('hiringOrganization', {})
    if isinstance(company, dict):
        company = company.get('name', '')
    for field, value, limit in (
        ('company', company, 120), ('job_title', posting.get('title'), 160),
    ):
        text = clean_text(value, limit)
        if len(text) >= 2:
            data[field] = text

    locations = list(dict.fromkeys(
        location for value in as_list(posting.get('jobLocation', []))
        if (location := location_text(value))
    ))
    location_types = {
        value.rsplit('/', 1)[-1].upper().replace('-', '_').replace(' ', '_')
        for value in as_list(posting.get('jobLocationType', [])) if isinstance(value, str)
    }
    work_modes = {
        {'TELECOMMUTE': 'remote', 'REMOTE': 'remote', 'HYBRID': 'hybrid', 'ON_SITE': 'onsite', 'ONSITE': 'onsite'}[value]
        for value in location_types if value in {'TELECOMMUTE', 'REMOTE', 'HYBRID', 'ON_SITE', 'ONSITE'}
    }
    if len(work_modes) == 1:
        data['work_mode'] = work_modes.pop()
    remote = data.get('work_mode') == 'remote'
    if remote:
        if not locations:
            locations = [country_name(value) for value in as_list(posting.get('applicantLocationRequirements', []))]
        locations = [location for location in locations if location]
        locations.append('Remote')
    location = clean_text(' / '.join(locations), 150)
    if location:
        data['location'] = location
    mapped_types = {
        EMPLOYMENT_TYPES[value.strip().upper().replace('-', '_').replace(' ', '_')]
        for value in as_list(posting.get('employmentType', []))
        if isinstance(value, str)
        and value.strip().upper().replace('-', '_').replace(' ', '_') in EMPLOYMENT_TYPES
    }
    if len(mapped_types) == 1:
        data['employment_type'] = mapped_types.pop()

    salaries = as_list(posting.get('baseSalary', []))
    if len(salaries) == 1 and isinstance(salaries[0], dict):
        salary = salaries[0]
        value = salary.get('value', {})
        if not isinstance(value, dict):
            value = {'value': value}
        minimum = salary_number(value.get('minValue'))
        maximum = salary_number(value.get('maxValue'))
        if minimum and maximum and Decimal(minimum) > Decimal(maximum):
            warnings.append('The salary range could not be imported. Enter it manually if needed.')
        else:
            if not minimum and not maximum:
                minimum = salary_number(value.get('value'))
                if minimum:
                    warnings.append('A single salary amount was imported as the minimum. Review it before saving.')
            if minimum:
                data['salary_min'] = minimum
            if maximum:
                data['salary_max'] = maximum
            if minimum or maximum:
                currency = salary.get('currency', '')
                if isinstance(currency, str) and re.fullmatch(r'[A-Za-z]{3}', currency):
                    data['currency'] = currency.upper()
                unit = clean_text(value.get('unitText', ''), 20)
                if unit:
                    warnings.append(f'The salary is listed per {unit.lower()}. Review the amount and period before saving.')
    return data, warnings


def source_name(url, company=''):
    host = urlsplit(url).hostname.lower()
    for domain, name in PROVIDERS.items():
        if host == domain or host.endswith('.' + domain):
            return name
    if company and host.split('.')[0] in {'jobs', 'careers'}:
        return clean_text(f'{company} careers', 80) or host[:80]
    return host[:80]


def parse_job_html(html, url):
    parser = JobPageParser()
    parser.feed(html)
    page_title = clean_text(''.join(parser.title), 300).lower()
    if any(marker in page_title for marker in (
        'just a moment', 'access denied', 'captcha', 'sign in', 'log in', 'verify you are human',
    )):
        raise JobImportError()
    postings = []
    for script in parser.scripts:
        try:
            for posting in find_job_postings(json.loads(script)):
                if posting not in postings:
                    postings.append(posting)
                    if len(postings) > 100:
                        raise JobImportError()
        except (ValueError, RecursionError):
            continue
    had_postings = bool(postings)
    if len(postings) > 1:
        # Listing/search pages can contain many jobs; only select an exact URL match.
        targets = {urlunsplit(urlsplit(url)._replace(fragment=''))}
        canonical = urljoin(url, parser.canonical)
        canonical_parts = urlsplit(canonical)
        current_parts = urlsplit(url)
        if canonical_parts.netloc == current_parts.netloc and canonical_parts.path == current_parts.path:
            targets.add(urlunsplit(canonical_parts._replace(fragment='')))
        postings = [
            posting for posting in postings
            if any(isinstance(posting.get(key), str) and
                   urlunsplit(urlsplit(urljoin(url, posting[key]))._replace(fragment='')) in targets
                   for key in ('url', '@id'))
        ]
    if len(postings) == 1:
        data, warnings = normalize_job(postings[0])
    else:
        data, warnings = {}, []
    if not had_postings or len(postings) == 1:
        title = clean_text(parser.metadata.get('og:title') or ''.join(parser.title), 285)
        match = re.fullmatch(r'(.+?) at (.+)', title)
        if match and not re.search(r'\b(login|sign in|captcha|access denied|just a moment|careers|job search|jobs|vacancies)\b', title, re.I):
            fallback_title = clean_text(match[1], 160)
            fallback_company = clean_text(match[2], 120)
            if (
                data.get('job_title', fallback_title) == fallback_title
                and data.get('company', fallback_company) == fallback_company
            ):
                if len(fallback_title) >= 2:
                    data.setdefault('job_title', fallback_title)
                if len(fallback_company) >= 2:
                    data.setdefault('company', fallback_company)
    if not any(data.get(field) for field in ('company', 'job_title', 'location')):
        raise JobImportError()
    data['source'] = source_name(url, data.get('company', ''))
    data['job_url'] = url
    if not all(data.get(field) for field in ('company', 'job_title', 'location')):
        warnings.append('Some details could not be detected. Complete the remaining fields manually.')
    return {'data': data, 'imported_fields': list(data), 'warnings': warnings}


def import_job_details(url):
    html, final_url = fetch_public_html(url)
    try:
        result = parse_job_html(html, final_url)
    except (ValueError, RecursionError):
        raise JobImportError() from None
    result['data']['job_url'] = url
    return result
