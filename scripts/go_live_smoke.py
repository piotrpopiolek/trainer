#!/usr/bin/env python3
"""Preflight smoke for F1.prod dogfood / go-live (unauthenticated + local gates).

Usage (stack up on PUBLIC_ORIGIN, default https://localhost):

  python scripts/go_live_smoke.py
  python scripts/go_live_smoke.py --origin https://app.example.com
"""

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _ensure_backup_passphrase(env_path: Path, env: dict[str, str]) -> dict[str, str]:
    if env.get("BACKUP_ENCRYPTION_PASSPHRASE"):
        return env
    phrase = secrets.token_hex(24)
    with env_path.open("a", encoding="utf-8") as fh:
        if env_path.stat().st_size > 0:
            fh.write("\n")
        fh.write(f"BACKUP_ENCRYPTION_PASSPHRASE={phrase}\n")
    env["BACKUP_ENCRYPTION_PASSPHRASE"] = phrase
    print("wrote BACKUP_ENCRYPTION_PASSPHRASE into .env (gitignored)")
    return env


def _load_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def _http(
    origin: str, path: str, *, method: str = "GET", follow: bool = False
) -> tuple[int, dict[str, str], bytes]:
    url = origin.rstrip("/") + path
    req = urllib.request.Request(url, method=method)
    ctx = None
    try:
        import ssl

        ctx = ssl.create_default_context()
        if "localhost" in origin or "127.0.0.1" in origin:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
    except Exception:
        ctx = None

    handlers: list[urllib.request.BaseHandler] = []
    if ctx is not None:
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    if not follow:

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
                raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)

        handlers.append(_NoRedirect())

    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(req, timeout=15) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            status = getattr(resp, "status", None) or resp.getcode()
            return int(status), headers, resp.read()
    except urllib.error.HTTPError as exc:
        headers = {k.lower(): v for k, v in exc.headers.items()} if exc.headers else {}
        body = exc.read() if exc.fp else b""
        return int(exc.code), headers, body


def _ok(name: str, detail: str = "") -> None:
    msg = f"ok  {name}" + (f" - {detail}" if detail else "")
    print(msg)


def _fail(name: str, detail: str) -> None:
    print(f"FAIL {name} - {detail}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--origin",
        default=os.environ.get("PUBLIC_ORIGIN", "https://localhost"),
        help="Same-origin base URL (default PUBLIC_ORIGIN or https://localhost)",
    )
    parser.add_argument(
        "--skip-compose",
        action="store_true",
        help="Skip docker compose catalog count check",
    )
    parser.add_argument(
        "--ensure-backup-passphrase",
        action="store_true",
        help="If BACKUP_ENCRYPTION_PASSPHRASE missing, append a random one to .env",
    )
    args = parser.parse_args()
    origin: str = args.origin
    env_path = ROOT / ".env"
    env = _load_dotenv(env_path)
    if args.ensure_backup_passphrase:
        env = _ensure_backup_passphrase(env_path, env)
    failures = 0

    # --- env secrets (local dogfood) ---
    if not env.get("GOOGLE_CLIENT_ID"):
        _fail("env.google_client_id", "set GOOGLE_CLIENT_ID in .env")
        failures += 1
    else:
        _ok("env.google_client_id")

    if not env.get("GOOGLE_CLIENT_SECRET"):
        _fail("env.google_client_secret", "set GOOGLE_CLIENT_SECRET in .env")
        failures += 1
    else:
        _ok("env.google_client_secret")

    if not env.get("CSRF_SECRET"):
        _fail("env.csrf_secret", "set CSRF_SECRET in .env")
        failures += 1
    else:
        _ok("env.csrf_secret")

    if not env.get("BACKUP_ENCRYPTION_PASSPHRASE"):
        _fail(
            "env.backup_passphrase",
            "set BACKUP_ENCRYPTION_PASSPHRASE (openssl rand -hex 24)",
        )
        failures += 1
    else:
        _ok("env.backup_passphrase")

    # --- HTTP ---
    code, _, body = _http(origin, "/api/health")
    if code == 200 and b'"status"' in body and b"ok" in body:
        _ok("http.health", str(code))
    else:
        _fail("http.health", f"status={code} body={body[:120]!r}")
        failures += 1

    code, _, body = _http(origin, "/api")
    if code == 200 and b"trainer-api" in body:
        _ok("http.api_root", str(code))
    else:
        _fail("http.api_root", f"status={code}")
        failures += 1

    code, _, _ = _http(origin, "/api/auth/me")
    if code in {401, 403}:
        _ok("http.me_unauth", str(code))
    else:
        _fail("http.me_unauth", f"expected 401/403, got {code}")
        failures += 1

    code, headers, _ = _http(origin, "/api/auth/google/start", follow=False)
    loc = headers.get("location", "")
    if code in {301, 302, 303, 307, 308} and "accounts.google.com" in loc:
        _ok("http.oauth_start", f"google redirect ({code})")
    else:
        _fail(
            "http.oauth_start",
            f"expected redirect to Google, got {code} location={loc[:80]!r}",
        )
        failures += 1

    code, _, body = _http(origin, "/api/legal/health-disclaimer")
    if code in {401, 403}:
        _ok("http.legal_disclaimer_auth_gate", str(code))
    else:
        _fail(
            "http.legal_disclaimer_auth_gate",
            f"expected 401/403 (auth required), got {code}",
        )
        failures += 1

    # --- content gate ---
    gate_env = {**os.environ, "TRAINER_CONTENT_GATE_STRICT": "1"}
    gate = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_content_gate.py")],
        cwd=ROOT,
        env=gate_env,
        capture_output=True,
        text=True,
        check=False,
    )
    if gate.returncode == 0:
        _ok("content_gate", (gate.stdout or gate.stderr).strip().splitlines()[-1] if (gate.stdout or gate.stderr) else "ok")
    else:
        _fail("content_gate", (gate.stderr or gate.stdout or "failed").strip()[:200])
        failures += 1

    # --- catalog counts via compose ---
    if not args.skip_compose:
        sql = (
            "SELECT "
            "(SELECT COUNT(*) FROM exercises WHERE kind='cc')::text || '|' || "
            "(SELECT COUNT(*) FROM exercise_steps es "
            "JOIN exercises e ON e.id = es.exercise_id WHERE e.kind='cc')::text || '|' || "
            "(SELECT COUNT(*) FROM exercise_step_translations est "
            "JOIN exercise_steps es ON es.id = est.exercise_step_id "
            "JOIN exercises e ON e.id = es.exercise_id "
            "WHERE e.kind='cc' AND est.locale='pl-PL' AND est.content_status='ready')::text;"
        )
        comp = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "trainer",
                "-d",
                "trainer",
                "-Atc",
                sql,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        counts = (comp.stdout or "").strip()
        if comp.returncode == 0 and counts == "6|60|60":
            _ok("db.catalog_counts", counts)
        else:
            _fail(
                "db.catalog_counts",
                f"got={counts!r} rc={comp.returncode} err={(comp.stderr or '')[:160]}",
            )
            failures += 1

    if failures:
        print(f"go_live_smoke.fail count={failures}", file=sys.stderr)
        return 1
    print("go_live_smoke.ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
