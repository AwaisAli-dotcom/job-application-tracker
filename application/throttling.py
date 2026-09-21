import hashlib
import hmac
import ipaddress
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.shortcuts import render
from django.utils import timezone

from .models import RequestThrottle


def get_client_ip(request):
    candidates = []

    if settings.TRUST_VERCEL_PROXY:
        candidates.extend(
            [
                request.META.get('HTTP_X_VERCEL_FORWARDED_FOR'),
                request.META.get('HTTP_X_REAL_IP'),
            ]
        )

    candidates.append(request.META.get('REMOTE_ADDR'))

    for candidate in candidates:
        if not candidate:
            continue

        value = candidate.split(',')[0].strip()

        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            continue

    return 'unknown'


def _identifier_hash(scope, identifier):
    message = f'{scope}:{identifier}'.encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def consume_request_limit(scope, identifier, limit, window_seconds):
    now = timezone.now()
    cutoff = now - timedelta(seconds=window_seconds)
    identifier_hash = _identifier_hash(scope, identifier or 'unknown')

    with transaction.atomic():
        throttle, created = RequestThrottle.objects.select_for_update().get_or_create(
            scope=scope,
            identifier_hash=identifier_hash,
            defaults={
                'window_started': now,
                'request_count': 1,
            },
        )

        if created:
            return None

        if throttle.window_started <= cutoff:
            throttle.window_started = now
            throttle.request_count = 1
            throttle.save(update_fields=['window_started', 'request_count'])
            return None

        if throttle.request_count >= limit:
            reset_at = throttle.window_started + timedelta(seconds=window_seconds)
            return max(1, int((reset_at - now).total_seconds()))

        RequestThrottle.objects.filter(pk=throttle.pk).update(
            request_count=F('request_count') + 1
        )

    RequestThrottle.objects.filter(window_started__lt=now - timedelta(days=2)).delete()
    return None


def rate_limited_response(request, retry_after):
    response = render(request, '429.html', status=429)
    response['Retry-After'] = str(retry_after)
    return response


def limit_registration_requests(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.method == 'POST':
            retry_after = consume_request_limit(
                'registration_ip',
                get_client_ip(request),
                limit=5,
                window_seconds=3600,
            )

            if retry_after is not None:
                return rate_limited_response(request, retry_after)

        return view(request, *args, **kwargs)

    return wrapped
