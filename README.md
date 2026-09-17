# Job Application Tracker

A private Django web app for tracking job applications from saved roles through interviews, offers, rejections, and withdrawals. Each user's applications and related records are protected by server-side ownership checks.

## Features

- Public home, About, and Privacy pages
- Email-aware registration, login, POST logout, and account profile editing
- User-owned job applications with create, list, detail, edit, and delete workflows
- Search by company, title, and location
- Filters by status, employment type, and application date range
- Sorting and pagination with query parameter preservation
- User-scoped CSV export with spreadsheet-formula protection
- Dashboard metrics, response/interview/offer rates, monthly activity, recent applications, deadlines, interviews, and reminders
- Kanban board with secure drag-and-drop status updates and an accessible dropdown fallback
- Status history timeline
- Interview rounds with schedule, mode, interviewer, location/link, outcome, and notes
- Document-link/version metadata and in-app reminders
- Work mode, source, structured salary range, currency, and deadline fields
- Friendly form validation and compact inline errors
- Friendly 403, 404, and 500 pages
- Automated tests for authentication, ownership, CRUD, filters, dashboard, Kanban, exports, related records, validation, and database constraints

## Tech Stack

- Python
- Django
- SQLite for local development
- PostgreSQL-ready production configuration
- HTML, CSS, and small vanilla JavaScript
- WhiteNoise for production static files
- Gunicorn for production WSGI serving

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
- `LOG_LEVEL`: Console logging level, such as `INFO` or `WARNING`.

## Running Tests

```powershell
python manage.py check
python manage.py test
python manage.py makemigrations --check --dry-run
```

For deployment review:

```powershell
python manage.py check --deploy
```

## Production Notes

This project is prepared for provider-neutral Django deployment.

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

A normal release should run these commands before starting the web process:

```text
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy
```

The final host must provide HTTPS, PostgreSQL credentials, the deployed host name, and the trusted HTTPS origin.

## Security Model

- Private views require authentication.
- Every application lookup includes the current user.
- Interview, document, reminder, history, dashboard, Kanban, and export queries are user-scoped.
- Delete and status-changing actions require POST and Django CSRF protection.
- Passwords use Django's authentication system and are never stored as raw text.
- Secrets, SQLite data, virtual environments, collected static files, and uploads are ignored by Git.

## Project Structure

```text
config/          Django project settings and URL configuration
application/     Models, forms, views, tests, migrations, templates, and static CSS
requirements.txt Python dependencies
.env.example     Safe environment variable template
Procfile         Provider-neutral Gunicorn web process command
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

## Screenshots

Add repository screenshots or a short demo GIF after the final visual review, using only demo data. Do not capture real job-search notes, private links, or credentials.

## Known Limitations

- A live deployment requires a hosting account, PostgreSQL service, domain/host settings, and HTTPS configuration.
- Document tracking stores secure metadata and optional links. Binary uploads are intentionally disabled until private object storage is selected.
- Email reminders, OAuth, AI features, and a separate API are optional future work rather than MVP requirements.
