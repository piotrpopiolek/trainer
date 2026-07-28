"""Locale allowlist + resolver (FR-007)."""

from __future__ import annotations

SUPPORTED_LOCALES: frozenset[str] = frozenset({"pl-PL"})
DEFAULT_LOCALE = "pl-PL"


def canonicalize_locale(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    # BCP 47 light: language-Region
    parts = value.replace("_", "-").split("-")
    if len(parts) == 1:
        return parts[0].lower()
    return f"{parts[0].lower()}-{parts[1].upper()}"


def resolve_locale(
    *,
    requested: str | None,
    user_locale: str | None,
) -> tuple[str, str]:
    """Return (requested_locale, resolved_locale). F1 only supports pl-PL."""
    preferred = canonicalize_locale(requested) or canonicalize_locale(user_locale) or DEFAULT_LOCALE
    requested_out = preferred
    if preferred in SUPPORTED_LOCALES:
        return requested_out, preferred
    return requested_out, DEFAULT_LOCALE
