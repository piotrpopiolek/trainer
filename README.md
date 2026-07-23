# Trainer

[![Status](https://img.shields.io/badge/status-pre--scaffold-yellow)](#project-status)
[![Phase](https://img.shields.io/badge/phase-1%20MVP%20planning-blue)](#project-scope)
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

**Phase 1 (MVP)** focuses on Google OAuth, onboarding, the CC program (6 exercises × 10 steps), a **server-side** deterministic progression engine, session logging, up to 10 satellite exercises, body measurements, offline sync (outbox / revision-based last-write-wins; sessions/measurements queue offline — progression evaluated only after sync on the backend), and health/privacy compliance.

**Phase 2+** adds a premium AI session coach, Garmin read-only recovery signals, rule-based Web Push, trend charts, YouTube-assisted exercise creation, billing, Redis/ARQ workers, and Cloudflare R2.

Product language (UI and exercise copy) is Polish. Copy is original and CC-structure–inspired; it does not quote the book verbatim.

This app is **not** a medical device and does not replace professional advice. Rehabilitation-tagged satellites are supplements, not treatment.

### Documentation

| Document | Description |
|----------|-------------|
| [docs/prd.md](docs/prd.md) | Product requirements (features, user stories, metrics) |
| [docs/db-plan.md](docs/db-plan.md) | PostgreSQL schema plan (MVP) |

## Tech stack

Planned stack (from the PRD). Application source, `package.json`, and `.nvmrc` are not in the repository yet.

### Frontend (Phase 1)

| Area | Choice |
|------|--------|
| App | React PWA (mobile-first) |
| Build | Vite + TypeScript |
| PWA | `vite-plugin-pwa` |
| UI | Tailwind CSS, shadcn/ui, Lucide React |
| Server state | TanStack Query |
| Client / offline UI | Zustand + IndexedDB + outbox |
| Forms | React Hook Form + Zod |

### Backend (Phase 1)

| Area | Choice |
|------|--------|
| API | FastAPI + Pydantic v2 |
| ORM | SQLAlchemy 2.0 + Alembic |
| Database | PostgreSQL + JSONB |
| Progression | Server-only `ProgressionEngine`; versioned JSON contracts (`schema_version`) + `rules_snapshot` on logs |
| Tooling | uv, Ruff, mypy, pytest |
| Auth (MVP) | Google OAuth only |

### Infrastructure

| Phase | Components |
|-------|------------|
| Phase 1 | Docker / Compose, GitHub Actions, OpenAPI |
| Phase 2+ | Redis + ARQ, Cloudflare R2, OpenTelemetry + Prometheus + Grafana |

**Out of Phase 1:** Apple Sign In, native iOS/Android apps, Redis/ARQ/R2, LLM agent, Garmin integration, Web Push, progress photos.

## Getting started locally

> **Note:** The app is not scaffolded yet. There is no runnable `frontend/` or `backend/` package in this repo. The steps below describe the intended local workflow once the stack is initialized.

### Prerequisites (planned)

- Node.js (version will be pinned in `.nvmrc` when the frontend is scaffolded)
- Python 3.12+ and [uv](https://github.com/astral-sh/uv)
- Docker and Docker Compose
- Google OAuth credentials (for auth)

### Planned setup

```bash
# Clone
git clone <repository-url>
cd trainer

# Frontend (after scaffold)
# nvm use          # respects .nvmrc when present
# cd frontend && npm install && npm run dev

# Backend (after scaffold)
# docker compose up -d db api
# docker compose run --rm api alembic upgrade head
```

Migrations and backend tests should run **inside Docker**, matching CI/production, once compose services exist.

Until scaffold lands, use the PRD as the source of truth for behavior and phases:

```bash
# Product docs only
open docs/prd.md   # or view in your editor
```

## Available scripts

No `package.json` or root `Makefile` is present yet. Expected scripts after scaffolding:

### Frontend (typical Vite / React)

| Script | Purpose |
|--------|---------|
| `npm run dev` | Start Vite development server |
| `npm run build` | Production build |
| `npm run preview` | Preview production build |
| `npm run lint` | Lint TypeScript / ESLint |
| `npm run test` | Frontend unit tests (when added) |

### Backend (typical)

| Command | Purpose |
|---------|---------|
| `docker compose up -d` | Start API + PostgreSQL |
| `docker compose run --rm api alembic upgrade head` | Apply migrations |
| `docker compose run --rm api pytest` | Run backend tests |
| `uv run ruff check` / `uv run mypy` | Lint and type-check (host tooling; runtime tests in Docker) |

This section will be updated when real scripts are added to the repository.

## Project scope

### In scope — Phase 1 (MVP)

- React PWA (installable, mobile-first)
- Google OAuth (no email/password; no Apple Sign In)
- CC program: 6 big exercises × 10 steps, 3-day split
- Deterministic progression engine **on the backend only** (versioned JSONB rules + `schema_version` contracts; `rules_snapshot` on session logs; no dual JS engine)
- Fast session logging (&lt; 3 minutes target)
- Up to 10 satellite exercises (types B/C, including **daily** schedule)
- Body measurements (weight, waist, biceps; optional chest, thigh, neck)
- Offline support with outbox sync (revision-based last-write-wins): queue sessions/measurements offline; **progression runs after sync on the server**
- Health disclaimer and privacy policy

### In scope — Phase 2

- AI agent (premium): next-session proposal with rationale
- YouTube link → satellite exercise draft (premium)
- Garmin read-only: sleep, HRV/Body Battery, training load (premium)
- Rule-based Web Push; body-measurement reminders
- Trend charts (training + body)
- Premium subscription gating
- Cloudflare R2, Redis + ARQ

### Explicitly out of scope (Phases 1–2)

- Apple OAuth (Phase 3+)
- Native mobile apps
- Progress photos
- Trainer / multi-client coaching
- Medical diagnosis or treatment claims
- Writing workouts back to Garmin calendar
- Verbatim Convict Conditioning book text

## Project status

| Item | Status |
|------|--------|
| Product requirements | Done — [docs/prd.md](docs/prd.md) |
| Schema plan | Done — [docs/db-plan.md](docs/db-plan.md) |
| Cursor project rules | Done — `.cursor/rules/` |
| Application code (frontend / backend) | Not started |
| `package.json` / `.nvmrc` | Not present |
| Docker Compose / CI | Not present |
| License file | Not chosen |

Current focus: **Phase 1 MVP design complete; implementation pending scaffolding.**

## License

License is **TBD**. No `LICENSE` file has been added yet. Do not assume open-source terms until a license is committed.

---

*Not medical advice. Trainer does not diagnose or treat conditions.*
