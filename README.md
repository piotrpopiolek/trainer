# Trainer

[![Status](https://img.shields.io/badge/status-scaffold-yellow)](#project-status)
[![Phase](https://img.shields.io/badge/phase-1%20MVP%20F1.0-blue)](#project-scope)
[![Docs](https://img.shields.io/badge/docs-PRD-informational)](docs/prd.md)
[![License](https://img.shields.io/badge/license-TBD-lightgrey)](#license)

Progressive Web App for tracking calisthenics progression (Convict Conditioning–style programs), custom satellite exercises, body measurements, and — in later phases — an AI coach and Garmin recovery data.

## Table of contents

- [Project description](#project-description)
- [Tech stack](#tech-stack)
- [Getting started locally](#getting-started-locally)
- [Available scripts](#available-scripts)
- [Project scope](#project-scope)
- [Project status](#project-status)
- [License](#license)

## Project description

Trainer helps an individual athlete follow a step-based bodyweight progression program inspired by Convict Conditioning (“Skazany na trening”), log workouts quickly (including offline), track custom satellite work (mobility, prehab, loaded auxiliaries), and record body measurements (weight, waist, biceps, and more).

**Phase 1 (MVP)** focuses on Google OAuth, onboarding, the CC program (6 exercises × 10 steps), a **server-side** deterministic progression engine, session logging, up to 10 satellite exercises, body measurements, offline sync (outbox / revision-based last-write-wins; sessions/measurements queue offline — progression evaluated only after sync on the backend), and health/privacy compliance. Delivery is staged: **F1.0 → F1.1 → F1.prod** (`docs/prd.md` §1.4a / FR-084).

**Phase 2+** adds a premium AI session coach, Garmin read-only recovery signals, rule-based Web Push, trend charts, YouTube-assisted exercise creation, billing, Redis/ARQ workers, and Cloudflare R2.

Product language (UI and exercise copy) is Polish. Copy is original and CC-structure–inspired; it does not quote the book verbatim.

This app is **not** a medical device and does not replace professional advice. Rehabilitation-tagged satellites are supplements, not treatment.

### Documentation

| Document | Description |
|----------|-------------|
| [docs/prd.md](docs/prd.md) | Product requirements (features, user stories, metrics) |
| [docs/db-plan.md](docs/db-plan.md) | PostgreSQL schema plan (MVP) |

## Tech stack

### Frontend (Phase 1)

| Area | Choice |
|------|--------|
| App | React PWA (mobile-first) |
| Build | Vite + TypeScript (strict) |
| PWA | `vite-plugin-pwa` |
| UI | Tailwind CSS (shadcn/ui primitives as features land) |
| Server state | TanStack Query |
| Client / offline UI | Zustand + IndexedDB + outbox |
| Forms | React Hook Form + Zod |
| Localization | `react-i18next`; F1 ships `pl-PL` |
| Frontend tests | Vitest (coverage ≥80%) + Playwright (E2E against Compose same-origin) |

### Backend (Phase 1)

| Area | Choice |
|------|--------|
| API | FastAPI + Pydantic v2 |
| ORM | SQLAlchemy 2.0 (async) + Alembic |
| Database | PostgreSQL 16 + JSONB |
| Tooling | uv, Ruff, mypy (strict), pytest + pytest-cov (`fail_under = 80`) |
| Auth (MVP) | Google OAuth (Auth Code + PKCE) — not wired yet |

### Infrastructure

| Phase | Components |
|-------|------------|
| Phase 1 | Docker Compose + Caddy (same-origin `/` + `/api`), GitHub Actions (next), PG backup/restore |
| Phase 2+ | Redis + ARQ, Cloudflare R2, OpenTelemetry |

## Getting started locally

### Prerequisites

- Node.js 24 (see `.nvmrc`) and npm
- Docker and Docker Compose
- Google OAuth credentials (when auth is implemented)

### Setup

```bash
cp .env.example .env
docker compose up -d --build
```

Same-origin stack: **https://localhost** (Caddy) → PWA (`web`) and `/api/*` (`api`).

Caddy uses a **local CA**. On first visit Windows browsers show a certificate warning until you trust it:

```powershell
powershell -ExecutionPolicy Bypass -File infra/caddy/trust-root.ps1
```

Then restart the browser and open https://localhost. (Cursor Simple Browser often stays blank on untrusted TLS — use Chrome/Edge after trusting the CA.)

```bash
# Migrations (once Alembic revisions exist)
docker compose run --rm api alembic upgrade head

# Backend tests / lint (inside Compose — matches CI)
docker compose run --rm api pytest
docker compose run --rm api ruff check backend
docker compose run --rm api mypy

# Frontend (host)
cd frontend && npm ci
npm run test:coverage
npm run dev   # optional Vite-only; prefer Compose for cookie/same-origin parity
```

Host Postgres tooling (optional) maps to `localhost:5433`.

## Available scripts

### Makefile

| Target | Purpose |
|--------|---------|
| `make up` | `docker compose up -d --build` |
| `make down` | Stop stack |
| `make test` | Backend pytest in Compose |
| `make test-idor` | `pytest -m idor` |
| `make migrate` | `alembic upgrade head` |

### Frontend (`frontend/`)

| Script | Purpose |
|--------|---------|
| `npm run dev` | Vite dev server (proxies `/api` → `:8000`) |
| `npm run build` | Production build |
| `npm run test` / `test:coverage` | Vitest |
| `npm run test:e2e` | Playwright (Compose base URL) |

### Backend (Compose)

| Command | Purpose |
|---------|---------|
| `docker compose run --rm api pytest` | Tests + coverage ≥80% |
| `docker compose run --rm api pytest -m idor` | IDOR suite |
| `docker compose run --rm api alembic upgrade head` | Migrations |

## Project scope

### In scope — Phase 1 (MVP)

- React PWA (installable, mobile-first)
- Google OAuth (no email/password; no Apple Sign In)
- CC program: 6 big exercises × 10 steps, 3-day split
- Deterministic progression engine **on the backend only**
- Fast session logging (&lt; 3 minutes target)
- Up to 10 satellite exercises
- Body measurements
- Offline support with outbox sync
- Health disclaimer and privacy policy
- Staged delivery **F1.0 → F1.1 → F1.prod**

### Explicitly out of scope (Phases 1–2)

- Apple OAuth (Phase 3+)
- Native mobile apps
- Progress photos
- Trainer / multi-client coaching
- Medical diagnosis or treatment claims
- Redis/ARQ/R2 in Phase 1

## Project status

| Item | Status |
|------|--------|
| Product requirements | Done — [docs/prd.md](docs/prd.md) |
| Schema plan | Done — [docs/db-plan.md](docs/db-plan.md) |
| Cursor project rules | Done — `.cursor/rules/` |
| Monorepo scaffold | Done — `backend/`, `frontend/`, `infra/`, Compose + Caddy |
| CI (GitHub Actions) | Done — `.github/workflows/ci.yml` + weekly `security.yml` |
| DB core (auth/legal/onboarding/RLS) | Done — Alembic `20260726_0001` |
| Catalog / sessions / sync schema | Not started |
| License file | Not chosen |

Current focus: **Phase 1 F1.0 — next is db-catalog-sync migrations.**

## License

License is **TBD**. No `LICENSE` file has been added yet.

---

*Not medical advice. Trainer does not diagnose or treat conditions.*
