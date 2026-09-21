"""Run with: python -m unittest discover -s tests/e2e -v"""

import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / '.e2e-artifacts'
PASSWORD = f'E2eSafePass{secrets.token_urlsafe(12)}!'
CHANGED_PASSWORD = f'ChangedE2ePass{secrets.token_urlsafe(12)}!'
RESET_PASSWORD = f'ResetE2ePass{secrets.token_urlsafe(12)}!'


class BrowserJourneys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.external_url = os.getenv('E2E_BASE_URL', '').rstrip('/')
        cls.temp_dir = tempfile.TemporaryDirectory(prefix='job-tracker-e2e-')
        cls.server = None
        cls.server_log = None
        cls.failed = False

        if cls.external_url:
            host = urlparse(cls.external_url).hostname
            if host not in {'127.0.0.1', 'localhost'} and os.getenv('E2E_ALLOW_EXTERNAL_WRITES') != '1':
                raise RuntimeError('External E2E writes require E2E_ALLOW_EXTERNAL_WRITES=1.')
            cls.base_url = cls.external_url
        else:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]

            cls.base_url = f'http://127.0.0.1:{port}'
            env = os.environ.copy()
            env.update({
                'DATABASE_URL': '',
                'DEBUG': 'True',
                'SECRET_KEY': secrets.token_urlsafe(60),
                'ALLOWED_HOSTS': '127.0.0.1,localhost',
                'EMAIL_BACKEND': 'django.core.mail.backends.console.EmailBackend',
                'E2E_DATABASE_PATH': str(Path(cls.temp_dir.name) / 'e2e.sqlite3'),
                'E2E_MEDIA_ROOT': str(Path(cls.temp_dir.name) / 'media'),
                'PYTHONUNBUFFERED': '1',
            })
            env.pop('VERCEL', None)
            cls.server_log = open(Path(cls.temp_dir.name) / 'server.log', 'w+', encoding='utf-8')
            subprocess.run(
                [sys.executable, 'manage.py', 'migrate', '--noinput'],
                cwd=ROOT, env=env, check=True, stdout=cls.server_log, stderr=subprocess.STDOUT,
            )
            cls.server = subprocess.Popen(
                [sys.executable, 'manage.py', 'runserver', f'127.0.0.1:{port}', '--noreload'],
                cwd=ROOT, env=env, stdout=cls.server_log, stderr=subprocess.STDOUT,
            )

            for _ in range(60):
                if cls.server.poll() is not None:
                    raise RuntimeError('The isolated Django server exited before browser tests began.')
                try:
                    with urlopen(cls.base_url, timeout=1) as response:
                        if response.status == 200:
                            break
                except (OSError, URLError):
                    time.sleep(0.25)
            else:
                raise RuntimeError('The isolated Django server did not start.')

        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'browser'):
            cls.browser.close()
            cls.playwright.stop()
        if cls.server:
            cls.server.terminate()
            try:
                cls.server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.server.kill()
                cls.server.wait(timeout=10)
        if cls.server_log:
            cls.server_log.flush()
            if cls.failed:
                ARTIFACTS.mkdir(exist_ok=True)
                shutil.copyfile(cls.server_log.name, ARTIFACTS / 'server.log')
            cls.server_log.close()
        cls.temp_dir.cleanup()

    def setUp(self):
        self.context = self.browser.new_context(
            base_url=self.base_url,
            viewport={'width': 1440, 'height': 900},
            timezone_id='Europe/Vilnius',
            accept_downloads=True,
        )
        self.context.tracing.start(screenshots=True, snapshots=True, sources=True)
        self.page = self.context.new_page()
        self.page_errors = []
        self.page.on('pageerror', lambda error: self.page_errors.append(str(error)))

    def tearDown(self):
        failures = self._outcome.result.failures + self._outcome.result.errors
        failed = any(test is self for test, _ in failures)
        if failed:
            type(self).failed = True
            ARTIFACTS.mkdir(exist_ok=True)
            self.page.screenshot(path=str(ARTIFACTS / f'{self._testMethodName}.png'), full_page=True)
            self.context.tracing.stop(path=str(ARTIFACTS / f'{self._testMethodName}.zip'))
        else:
            self.context.tracing.stop()
        self.context.close()
        self.assertEqual(self.page_errors, [], 'Unexpected browser JavaScript errors')

    def register(self):
        username = f'e2e_{uuid4().hex[:10]}'
        self.page.goto('/accounts/register/')
        self.page.locator('[name="username"]').fill(username)
        self.page.locator('[name="email"]').fill(f'{username}@example.test')
        self.page.locator('[name="password1"]').fill(PASSWORD)
        self.page.locator('[name="password2"]').fill(PASSWORD)
        self.page.get_by_role('button', name='Create Account').click()
        expect(self.page).to_have_url(re.compile(r'/dashboard/$'))
        return username

    def add_application(self, company):
        self.page.goto('/add/')
        self.page.locator('[name="company"]').fill(company)
        self.page.locator('[name="job_title"]').fill('Python Developer')
        self.page.locator('[name="location"]').fill('Vilnius')
        self.page.locator('[name="application_date"]').fill(
            datetime.now(ZoneInfo('Europe/Vilnius')).date().isoformat()
        )
        self.page.locator('[name="status"]').select_option('saved')
        self.page.get_by_role('button', name='Save Application').click()
        expect(self.page).to_have_url(re.compile(r'/applications/$'))
        card = self.page.locator('.job-card').filter(has_text=company)
        expect(card).to_be_visible()
        card.get_by_role('link', name='View').click()
        expect(self.page.get_by_role('heading', name=company)).to_be_visible()
        return urlparse(self.page.url).path

    def test_public_pages_and_mobile_layout(self):
        for path, title in (('/', 'Job Application Tracker'), ('/about/', 'About'), ('/privacy/', 'Privacy')):
            self.page.goto(path)
            expect(self.page.get_by_role('heading', name=title, exact=True)).to_be_visible()
            self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth'))
            self.assertEqual(self.page.locator('link[rel="canonical"]').count(), 1)

        self.page.goto('/sitemap.xml')
        self.assertIn('/about/', self.page.locator('body').inner_text())
        self.page.goto('/robots.txt')
        self.assertIn('Disallow: /applications/', self.page.locator('body').inner_text())

        mobile = self.browser.new_context(
            base_url=self.base_url,
            viewport={'width': 390, 'height': 844},
            device_scale_factor=1,
            is_mobile=True,
            has_touch=True,
        )
        try:
            mobile_page = mobile.new_page()
            for path in ('/', '/accounts/login/', '/accounts/register/', '/about/', '/privacy/'):
                mobile_page.goto(path)
                self.assertFalse(
                    mobile_page.evaluate('document.documentElement.scrollWidth > innerWidth'),
                    f'Horizontal overflow on {path}',
                )
        finally:
            mobile.close()

    def test_authentication_account_and_password_recovery(self):
        username = self.register()
        self.page.goto('/accounts/profile/')
        updated_name = f'{username}_new'
        self.page.locator('[name="username"]').fill(updated_name)
        self.page.get_by_role('button', name='Save Changes').click()
        expect(self.page.locator('[name="username"]')).to_have_value(updated_name)

        self.page.get_by_role('link', name='Change Password').click()
        self.page.locator('[name="old_password"]').fill(PASSWORD)
        self.page.locator('[name="new_password1"]').fill(CHANGED_PASSWORD)
        self.page.locator('[name="new_password2"]').fill(CHANGED_PASSWORD)
        self.page.get_by_role('button', name='Change Password').click()
        expect(self.page.get_by_role('heading', name='Password changed')).to_be_visible()

        self.page.get_by_role('button', name='Log out').click()
        expect(self.page).to_have_url(re.compile(r'/accounts/login/$'))
        self.page.locator('[name="username"]').fill(updated_name)
        self.page.locator('[name="password"]').fill('WrongPass123!')
        self.page.get_by_role('button', name='Log In').click()
        expect(self.page.locator('.errorlist')).to_be_visible()
        self.page.locator('[name="password"]').fill(CHANGED_PASSWORD)
        self.page.get_by_role('button', name='Log In').click()
        expect(self.page).to_have_url(re.compile(r'/dashboard/$'))

        self.page.get_by_role('button', name='Log out').click()
        self.page.get_by_role('link', name='Forgot password?').click()
        self.page.locator('[name="email"]').fill(f'{username}@example.test')
        self.page.get_by_role('button', name='Send Reset Link').click()
        expect(self.page.get_by_role('heading', name='Check your email')).to_be_visible()

        if self.server_log is None:
            self.skipTest('External environments do not expose the password-reset test email.')

        reset_path = None
        for _ in range(40):
            self.server_log.flush()
            log = Path(self.server_log.name).read_text(encoding='utf-8')
            log = re.sub(r'=\r?\n', '', log)
            match = re.search(r'/accounts/reset/[\w-]+/[\w-]+/', log)
            if match:
                reset_path = match.group(0)
                break
            time.sleep(0.25)
        self.assertIsNotNone(reset_path, 'Password-reset email was not written to the local console backend.')
        self.page.goto(reset_path)
        expect(self.page.get_by_role('heading', name='Choose a new password')).to_be_visible()
        self.page.locator('[name="new_password1"]').fill(RESET_PASSWORD)
        self.page.locator('[name="new_password2"]').fill(RESET_PASSWORD)
        self.page.get_by_role('button', name='Set New Password').click()
        expect(self.page.get_by_role('heading', name='Password reset complete')).to_be_visible()
        self.page.goto('/accounts/login/')
        self.page.locator('[name="username"]').fill(updated_name)
        self.page.locator('[name="password"]').fill(RESET_PASSWORD)
        self.page.get_by_role('button', name='Log In').click()
        expect(self.page).to_have_url(re.compile(r'/dashboard/$'))

    def test_application_workflow(self):
        self.register()
        company = f'E2E Company {uuid4().hex[:6]}'
        detail_path = self.add_application(company)
        self.page.get_by_role('link', name='Edit', exact=True).first.click()
        self.page.locator('[name="job_title"]').fill('Senior Python Developer')
        self.page.get_by_role('button', name='Save Changes').click()
        expect(self.page.locator('.job-card').filter(has_text=company)).to_contain_text('Senior Python Developer')

        self.page.locator('[name="search"]').fill(company)
        self.page.get_by_role('button', name='Search').click()
        expect(self.page.locator('.job-card')).to_have_count(1)
        self.page.locator('[name="status"]').select_option('saved')
        expect(self.page.locator('[name="search"]')).to_have_value(company)
        self.page.locator('[name="sort"]').select_option('company_az')
        expect(self.page.locator('[name="status"]')).to_have_value('saved')
        self.page.get_by_role('link', name='Clear').click()
        expect(self.page.locator('[name="search"]')).to_have_value('')

        with self.page.expect_download() as csv_download:
            self.page.get_by_role('link', name='Export CSV').click()
        self.assertTrue(csv_download.value.suggested_filename.endswith('.csv'))
        self.page.goto('/dashboard/')
        expect(self.page.get_by_role('heading', name='Dashboard')).to_be_visible()
        self.page.goto('/applications/kanban/')
        card = self.page.locator('.kanban-card').filter(has_text=company)
        card.locator('select[name="status"]').select_option('interview')
        expect(card.locator('.status-badge')).to_have_text('Interview')

        self.page.goto(detail_path)
        self.page.get_by_role('link', name='Add Interview').click()
        self.page.locator('[name="scheduled_at"]').fill(
            (datetime.now(ZoneInfo('Europe/Vilnius')) + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M')
        )
        self.page.get_by_role('button', name='Save Interview').click()
        interviews = self.page.locator('.activity-card').filter(has=self.page.get_by_role('heading', name='Interviews'))
        expect(interviews).not_to_contain_text('No interviews recorded yet.')
        interviews.get_by_role('link', name='Edit').click()
        self.page.locator('[name="interviewer"]').fill('E2E Interviewer')
        self.page.get_by_role('button', name='Save Interview').click()
        expect(interviews).to_contain_text('E2E Interviewer')
        interviews.get_by_role('link', name='Delete').click()
        self.page.get_by_role('button', name='Yes, delete it').click()
        expect(interviews).to_contain_text('No interviews recorded yet.')

        self.page.get_by_role('link', name='Add Reminder').click()
        self.page.locator('[name="title"]').fill('E2E follow-up')
        self.page.locator('[name="due_at"]').fill(
            (datetime.now(ZoneInfo('Europe/Vilnius')) + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M')
        )
        self.page.get_by_role('button', name='Save Reminder').click()
        reminders = self.page.locator('.activity-card').filter(has=self.page.get_by_role('heading', name='Reminders'))
        expect(reminders).to_contain_text('E2E follow-up')
        reminders.get_by_role('link', name='Edit').click()
        self.page.locator('[name="title"]').fill('E2E updated follow-up')
        self.page.get_by_role('button', name='Save Reminder').click()
        expect(reminders).to_contain_text('E2E updated follow-up')
        reminders.get_by_role('link', name='Delete').click()
        self.page.get_by_role('button', name='Yes, delete it').click()
        expect(reminders).to_contain_text('No reminders recorded yet.')

        self.page.get_by_role('link', name='Add Document').click()
        self.page.locator('[name="title"]').fill('E2E CV')
        self.page.locator('[name="file"]').set_input_files({
            'name': 'e2e-cv.txt', 'mimeType': 'text/plain', 'buffer': b'E2E demo CV only',
        })
        self.page.get_by_role('button', name='Save Document').click()
        documents = self.page.locator('.activity-card').filter(has=self.page.get_by_role('heading', name='Documents'))
        expect(documents).to_contain_text('E2E CV')
        with self.page.expect_download() as document_download:
            documents.get_by_role('link', name='Download').click()
        self.assertEqual(document_download.value.suggested_filename, 'e2e-cv.txt')
        documents.get_by_role('link', name='Edit').click()
        self.page.locator('[name="notes"]').fill('Updated E2E document')
        self.page.get_by_role('button', name='Save Document').click()
        expect(documents).to_contain_text('Updated E2E document')
        documents.get_by_role('link', name='Delete').click()
        self.page.get_by_role('button', name='Yes, delete it').click()
        expect(documents).to_contain_text('No documents recorded yet.')

        ARTIFACTS.mkdir(exist_ok=True)
        self.page.goto('/applications/')
        self.page.screenshot(path=str(ARTIFACTS / 'applications-desktop.png'), full_page=True)
        mobile = self.browser.new_context(
            base_url=self.base_url,
            storage_state=self.context.storage_state(),
            viewport={'width': 390, 'height': 844},
            device_scale_factor=1,
            is_mobile=True,
            has_touch=True,
        )
        try:
            mobile_page = mobile.new_page()
            for path in ('/dashboard/', '/applications/', detail_path, '/add/', '/accounts/profile/'):
                mobile_page.goto(path)
                self.assertFalse(
                    mobile_page.evaluate('document.documentElement.scrollWidth > innerWidth'),
                    f'Horizontal overflow on {path}',
                )
                if path == '/applications/':
                    mobile_page.screenshot(path=str(ARTIFACTS / 'applications-mobile.png'), full_page=True)
        finally:
            mobile.close()

        self.page.goto(detail_path)
        self.page.get_by_role('link', name='Delete', exact=True).first.click()
        self.page.get_by_role('button', name='Yes, delete it').click()
        expect(self.page.locator('.job-card').filter(has_text=company)).to_have_count(0)

    def test_second_user_cannot_access_private_records(self):
        self.register()
        company = f'Private E2E {uuid4().hex[:6]}'
        detail_path = self.add_application(company)
        app_id = detail_path.strip('/').split('/')[-1]
        self.page.get_by_role('link', name='Add Reminder').click()
        self.page.locator('[name="title"]').fill('Private reminder')
        self.page.locator('[name="due_at"]').fill(
            (datetime.now(ZoneInfo('Europe/Vilnius')) + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')
        )
        self.page.get_by_role('button', name='Save Reminder').click()
        reminder_href = self.page.locator('.activity-card').filter(
            has=self.page.get_by_role('heading', name='Reminders')
        ).get_by_role('link', name='Edit').get_attribute('href')

        self.page.get_by_role('link', name='Add Interview').click()
        self.page.locator('[name="scheduled_at"]').fill(
            (datetime.now(ZoneInfo('Europe/Vilnius')) + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M')
        )
        self.page.get_by_role('button', name='Save Interview').click()
        interview_href = self.page.locator('.activity-card').filter(
            has=self.page.get_by_role('heading', name='Interviews')
        ).get_by_role('link', name='Edit').get_attribute('href')

        self.page.get_by_role('link', name='Add Document').click()
        self.page.locator('[name="title"]').fill('Private E2E CV')
        self.page.locator('[name="file"]').set_input_files({
            'name': 'private-e2e.txt', 'mimeType': 'text/plain', 'buffer': b'Private test file',
        })
        self.page.get_by_role('button', name='Save Document').click()
        private_document = self.page.locator('.activity-card').filter(
            has=self.page.get_by_role('heading', name='Documents')
        )
        document_href = private_document.get_by_role('link', name='Download').get_attribute('href')
        document_edit_href = private_document.get_by_role('link', name='Edit').get_attribute('href')
        document_delete_href = private_document.get_by_role('link', name='Delete').get_attribute('href')

        self.page.get_by_role('button', name='Log out').click()
        self.page.goto(detail_path)
        expect(self.page).to_have_url(re.compile(r'/accounts/login/'))
        self.register()
        for path in (
            detail_path,
            f'/edit/{app_id}/',
            f'/delete/{app_id}/',
            f'/applications/{app_id}/interviews/add/',
            reminder_href,
            interview_href,
            document_href,
            document_edit_href,
            document_delete_href,
        ):
            response = self.page.goto(path)
            self.assertEqual(response.status, 404, path)

        self.page.goto('/applications/')
        expect(self.page.locator('.job-card').filter(has_text=company)).to_have_count(0)
        self.page.goto('/dashboard/')
        self.assertNotIn(company, self.page.locator('body').inner_text())
        self.page.goto('/applications/kanban/')
        expect(self.page.locator('.kanban-card').filter(has_text=company)).to_have_count(0)
        csrf_token = next(cookie['value'] for cookie in self.context.cookies() if cookie['name'] == 'csrftoken')
        response = self.context.request.post(
            f'{self.base_url}/applications/{app_id}/status/',
            data={'status': 'offer'},
            headers={'X-CSRFToken': csrf_token},
        )
        self.assertEqual(response.status, 404)
        self.page.goto('/applications/')
        with self.page.expect_download() as export_download:
            self.page.get_by_role('link', name='Export CSV').click()
        self.assertNotIn(company, Path(export_download.value.path()).read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
