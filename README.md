# Job Application Tracker

A private Django web app for tracking job applications from saved roles through interviews, offers, rejections, and withdrawals. Each user's applications and related records are protected by server-side ownership checks.

## Features

- Public home, About, and Privacy pages
- Email-aware registration, login, POST logout, account editing, password change, and email password reset
- User-owned job applications with create, list, detail, edit, and delete workflows
- Search by company, title, and location
- Filters by status, employment type, and application date range
- Sorting and pagination with query parameter preservation
- User-scoped CSV export with spreadsheet-formula protection
- Dashboard metrics, response/interview/offer rates, monthly activity, recent applications, deadlines, interviews, and reminders
- Kanban board with secure drag-and-drop status updates and an accessible dropdown fallback
- Status history timeline
- Interview rounds with schedule, mode, interviewer, location/link, outcome, and notes
- Private document uploads (up to 4 MB), document links, and in-app reminders
- Work mode, source, structured salary range, currency, and deadline fields
- Friendly form validation and compact inline errors
- Friendly 403, 404, and 500 pages
- Automated Django and Playwright browser tests for the main user journeys and ownership checks
- Public sitemap and robots.txt, public search metadata, and noindex metadata on private pages

## Tech Stack

- Python
- Django
- SQLite for local development
- Neon PostgreSQL in production
- HTML, CSS, and small vanilla JavaScript
- WhiteNoise for production static files
- Cloudflare R2 for private production uploads
- Brevo SMTP for production password-reset email (configured externally)
- django-axes and database-backed request throttling for sign-in and account recovery
- Gunicorn for production WSGI serving
- Vercel deployment from GitHub

## Local Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Create a local `.env` file using `.env.example`:

```powershell
Copy-Item .env.example .env
```

Set a real local `SECRET_KEY` in `.env`.

Run migrations:

```powershell
python manage.py migrate
```

Create an admin user if needed:

```powershell
python manage.py createsuperuser
```

Start the development server:

```powershell
python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000/
```

## Environment Variables

- `SECRET_KEY`: Required secret value for Django.
- `DEBUG`: `True` locally, `False` in production.
- `ALLOWED_HOSTS`: Comma-separated hostnames.
- `CSRF_TRUSTED_ORIGINS`: Comma-separated HTTPS origins for production.
- `DATABASE_URL`: PostgreSQL URL for production. Leave blank locally to use SQLite.
- `SECURE_SSL_REDIRECT`: Usually `True` in production.
- `SECURE_HSTS_SECONDS`: HSTS duration for HTTPS production deployments.
- `SECURE_HSTS_INCLUDE_SUBDOMAINS`: Whether HSTS includes subdomains.
- `SECURE_HSTS_PRELOAD`: Whether the domain is eligible for browser preload lists.
- `EMAIL_BACKEND`: SMTP or another production email backend when `DEBUG=False`.
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`: SMTP delivery settings.
- `DEFAULT_FROM_EMAIL`: Verified sender address for password-reset emails.
- `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`, `R2_ENDPOINT_URL`: Private production document storage.
- `LOG_LEVEL`: Console logging level, such as `INFO` or `WARNING`.

## Running Tests

```powershell
python manage.py check
python manage.py test
python manage.py makemigrations --check --dry-run
```

Browser tests use a separate temporary SQLite database and local server. They never use your normal `db.sqlite3`:

```powershell
pip install -r requirements-dev.txt
python -m playwright install chromium
python -m unittest discover -s tests/e2e -v
```

Demo screenshots and failure traces/logs are saved in ignored `.e2e-artifacts/`.
`E2E_BASE_URL` can point at another environment; writes to a non-local URL also require
`E2E_ALLOW_EXTERNAL_WRITES=1`. Do not aim the test suite at production unless you
deliberately want it to create and delete test accounts and records there.

For deployment review:

```powershell
python manage.py check --deploy
```

## Production Notes

The app is deployed on Vercel at
`https://job-application-tracker-six-ecru.vercel.app/`, with Neon PostgreSQL,
Cloudflare R2 uploads, and SMTP settings supplied through Vercel environment variables.

Production should use:

- `DEBUG=False`
- A strong `SECRET_KEY`
- PostgreSQL through `DATABASE_URL`
- Correct `ALLOWED_HOSTS`
- Correct `CSRF_TRUSTED_ORIGINS`
- HTTPS
- Secure cookies
- Collected static files
- Console logging connected to the host's log collector

Collect static files:

```powershell
python manage.py collectstatic --noinput
```

Typical production command:

```text
gunicorn config.wsgi:application
```

A production build runs database migrations and collects static files through `vercel.json`.
Migrations run only on production builds. Do not point preview environments at the
production database. For another host, a normal release should run:

```text
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy
```

The host must provide HTTPS, database and R2 credentials, SMTP credentials, the
deployed host name, and the trusted HTTPS origin. Never commit these values.

## Security Model

- Private views require authentication.
- Every application lookup includes the current user.
- Interview, document, reminder, history, dashboard, Kanban, and export queries are user-scoped.
- Delete and status-changing actions require POST and Django CSRF protection.
- Passwords use Django's authentication system and are never stored as raw text.
- Failed sign-ins have a temporary cooldown; registration and password-reset requests are rate limited.
- Uploaded files are validated by type and size; only owners can request a short-lived download URL.
- Secrets, SQLite data, virtual environments, collected static files, and uploads are ignored by Git.

## Project Structure

```text
config/          Django project settings and URL configuration
application/     Models, forms, views, tests, migrations, templates, and static CSS
requirements.txt Python dependencies
requirements-dev.txt Playwright browser-test dependencies
.env.example     Safe environment variable template
Procfile         Provider-neutral Gunicorn web process command
vercel.json      Production build and migration command
```

## Main URLs

- `/` - public home
- `/accounts/register/` - registration
- `/accounts/login/` - login
- `/dashboard/` - private dashboard
- `/applications/` - searchable application list and CSV export
- `/applications/kanban/` - status workflow board
- `/interviews/` - upcoming and past interview rounds
- `/admin/` - Django administration
- `/sitemap.xml` and `/robots.txt` - public search-engine discovery

## Screenshots

Add repository screenshots or a short demo GIF after the final visual review, using only demo data. Do not capture real job-search notes, private links, or credentials.

## External Checks

- Production email delivery and R2 upload/download need a real account-level smoke test; local tests use a console email backend and temporary file storage.
- Google Search Console needs your Google account and site verification before the public sitemap can be submitted.
- Email reminders, OAuth, AI features, and a separate API are outside the current project scope.
