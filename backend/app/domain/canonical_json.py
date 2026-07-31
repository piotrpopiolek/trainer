"""RFC 8785 JSON Canonicalization Scheme (JCS) for satellite config hashing."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any
from uuid import UUID

_ESCAPE = re.compile(r'[\x00-\x1f"\\]')


def _escape_string(value: str) -> str:
    def repl(match: re.Match[str]) -> str:
        ch = match.group(0)
        if ch == '"':
            return '\\"'
        if ch == "\\":
            return "\\\\"
        code = ord(ch)
        return f"\\u{code:04x}"

    return '"' + _ESCAPE.sub(repl, value) + '"'


def canonicalize(value: Any) -> str:
    """Serialize to RFC 8785 JCS UTF-8 text (no trailing whitespace)."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _escape_string(value)
    if isinstance(value, UUID):
        return _escape_string(str(value))
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("jcs_non_finite_number")
        # Satellite config forbids floats; keep strict.
        raise ValueError("jcs_float_forbidden")
    if isinstance(value, list):
        return "[" + ",".join(canonicalize(item) for item in value) + "]"
    if isinstance(value, dict):
        parts: list[str] = []
        for key in sorted(value.keys()):
            if not isinstance(key, str):
                raise ValueError("jcs_non_string_key")
            parts.append(_escape_string(key) + ":" + canonicalize(value[key]))
        return "{" + ",".join(parts) + "}"
    raise ValueError(f"jcs_unsupported_type:{type(value).__name__}")


def sha256_jcs(document: dict[str, Any]) -> bytes:
    """SHA-256 over UTF-8 JCS bytes (32 raw bytes)."""
    text = canonicalize(document)
    return hashlib.sha256(text.encode("utf-8")).digest()


def sha256_jcs_hex(document: dict[str, Any]) -> str:
    return sha256_jcs(document).hex()
