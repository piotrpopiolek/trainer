"""Auth / domain error codes (language-neutral)."""

from __future__ import annotations


class AuthError(Exception):
    def __init__(
        self,
        error_code: str,
        *,
        http_status: int = 401,
        retry_after: int | None = None,
    ) -> None:
        self.error_code = error_code
        self.http_status = http_status
        self.retry_after = retry_after
        super().__init__(error_code)


class OAuthNotConfiguredError(AuthError):
    def __init__(self) -> None:
        super().__init__("oauth_not_configured", http_status=503)


class RateLimitedError(AuthError):
    def __init__(self, *, retry_after: int = 60) -> None:
        super().__init__(
            "rate_limited",
            http_status=429,
            retry_after=retry_after,
        )


class CsrfError(AuthError):
    def __init__(self) -> None:
        super().__init__("csrf_invalid", http_status=403)


class NotFoundError(AuthError):
    def __init__(self) -> None:
        super().__init__("not_found", http_status=404)


class PayloadTooLargeError(AuthError):
    def __init__(self) -> None:
        super().__init__("payload_too_large", http_status=422)


class DomainError(Exception):
    def __init__(self, error_code: str, *, http_status: int = 422) -> None:
        self.error_code = error_code
        self.http_status = http_status
        super().__init__(error_code)


class LegalRequiredError(DomainError):
    def __init__(self) -> None:
        super().__init__("legal_required", http_status=403)
