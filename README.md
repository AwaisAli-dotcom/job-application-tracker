# Job Application Tracker

A private Django web app for tracking job applications from saved roles through applications, interviews, offers, rejections, and withdrawals.

## Features

- User registration, login, and POST logout
- User-owned job applications with create, list, detail, edit, and delete workflows
- Search by company, title, and location
- Filters by status, employment type, and application date range
- Sorting and pagination with query parameter preservation
- Dashboard metrics, status breakdown, monthly activity, recent applications, and upcoming interviews
- Kanban board with secure status updates and dropdown fallback
- Status history timeline
- Interview tracking with upcoming and past interview views
- Friendly form validation and compact inline errors
- Automated tests for authentication, ownership, CRUD, filters, dashboard, Kanban, status history, and interviews

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
- `EMAIL_BACKEND`: SMTP or another production email backend when `DEBUG=False`.

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

Collect static files:

```powershell
python manage.py collectstatic --noinput
```

Typical production command:

```text
gunicorn config.wsgi:application
```

## Project Structure

```text
config/          Django project settings and URL configuration
application/     Main app: models, forms, views, tests, templates, static CSS
requirements.txt Python dependencies
.env.example     Safe environment variable template
```

## Screenshots

Screenshots or a short demo GIF can be added here after final visual review.

## Known Limitations

- Live deployment requires selecting a hosting provider and setting real production environment variables.
- Document tracking and reminders are planned next portfolio upgrades.
- Actual file uploads are not enabled yet; this avoids storing private user files locally before production storage is chosen.
