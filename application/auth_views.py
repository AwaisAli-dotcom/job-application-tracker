from django.contrib.auth import views as auth_views

from .throttling import (
    consume_request_limit,
    get_client_ip,
    rate_limited_response,
)


class RateLimitedPasswordResetView(auth_views.PasswordResetView):
    def post(self, request, *args, **kwargs):
        client_ip = get_client_ip(request)
        email = request.POST.get('email', '').strip().lower()
        retry_after = consume_request_limit(
            'password_reset_ip',
            client_ip,
            limit=20,
            window_seconds=3600,
        )

        if retry_after is None:
            retry_after = consume_request_limit(
                'password_reset_email',
                email,
                limit=5,
                window_seconds=3600,
            )

        if retry_after is not None:
            return rate_limited_response(request, retry_after)

        return super().post(request, *args, **kwargs)


class RateLimitedPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    def post(self, request, *args, **kwargs):
        retry_after = consume_request_limit(
            'password_reset_confirm_ip',
            get_client_ip(request),
            limit=20,
            window_seconds=3600,
        )

        if retry_after is not None:
            return rate_limited_response(request, retry_after)

        return super().post(request, *args, **kwargs)
