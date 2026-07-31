"""Idempotent catalog + legal seed (FR-020 / FR-020a)."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.catalog import (
    Exercise,
    ExerciseStep,
    ExerciseStepTranslation,
    ExerciseTranslation,
    Program,
    ProgramDay,
    ProgramDayExercise,
    ProgramDayTranslation,
    ProgramTranslation,
)
from app.models.legal import LegalDocument, LegalDocumentTranslation
from app.models.progression import ProgressionSchema
from app.seed.ids import seed_id
from app.seed.loader import load_json

LOCALE_PL = "pl-PL"


def _threshold_dict(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "sets": int(raw["sets"]),
        "require_both_sides": bool(raw.get("require_both_sides", False)),
    }
    if raw.get("min_reps") is not None:
        out["min_reps"] = int(raw["min_reps"])
    if raw.get("min_duration_sec") is not None:
        out["min_duration_sec"] = int(raw["min_duration_sec"])
    return out


def rules_v2_from_standards(entry: dict[str, Any]) -> dict[str, Any]:
    progression = _threshold_dict(entry["progression"])
    return {
        "schema_version": 2,
        "standards": {
            "beginner": _threshold_dict(entry["beginner"]),
            "intermediate": _threshold_dict(entry["intermediate"]),
            "progression": progression,
        },
        "advance": progression,
        "regress": {"fail_sessions": 2},
        "goal": None,
    }


def legal_content_hash(title: str, body: str) -> bytes:
    """SHA-256 of canonical JSON {title,body} (NFC) → BYTEA (db-plan §1.3a)."""
    payload = {
        "body": unicodedata.normalize("NFC", body),
        "title": unicodedata.normalize("NFC", title),
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).digest()


async def seed_all(session: AsyncSession) -> dict[str, int]:
    entities = load_json("cc", "entities.json")
    pl = load_json("cc", "pl-PL", "catalog.json")
    standards_doc = load_json("cc", "step_standards.json")
    legal_docs = load_json("legal", "documents.json")
    legal_pl = load_json("legal", "pl-PL.json")

    standards_by_key = {
        (s["exercise_slug"], int(s["step_number"])): s for s in standards_doc["steps"]
    }

    counts = {
        "progression_schemas": 0,
        "programs": 0,
        "program_days": 0,
        "exercises": 0,
        "exercise_steps": 0,
        "translations": 0,
        "legal_documents": 0,
        "legal_translations": 0,
    }

    schema_ids: dict[tuple[str, int], Any] = {}
    for item in entities["progression_schemas"]:
        sid = seed_id("progression_schema", item["slug"], str(item["schema_version"]))
        await session.execute(
            insert(ProgressionSchema)
            .values(
                id=sid,
                slug=item["slug"],
                schema_version=item["schema_version"],
                description=item.get("description"),
            )
            .on_conflict_do_update(
                constraint="uq_progression_schemas_slug_version",
                set_={"description": item.get("description")},
            )
        )
        schema_ids[(item["slug"], item["schema_version"])] = sid
        counts["progression_schemas"] += 1

    default_schema_id = schema_ids[("cc_default", 2)]
    program_slug = entities["program"]["slug"]
    program_id = seed_id("program", program_slug)
    await session.execute(
        insert(Program)
        .values(
            id=program_id,
            slug=program_slug,
            is_system=bool(entities["program"].get("is_system", True)),
        )
        .on_conflict_do_update(
            constraint="uq_programs_slug",
            set_={"is_system": bool(entities["program"].get("is_system", True))},
        )
    )
    counts["programs"] += 1

    await session.execute(
        insert(ProgramTranslation)
        .values(
            program_id=program_id,
            locale=LOCALE_PL,
            name=pl["program"]["name"],
            description=pl["program"].get("description"),
            catalog_version=int(pl.get("catalog_version", 1)),
        )
        .on_conflict_do_update(
            index_elements=["program_id", "locale"],
            set_={
                "name": pl["program"]["name"],
                "description": pl["program"].get("description"),
                "catalog_version": int(pl.get("catalog_version", 1)),
            },
        )
    )
    counts["translations"] += 1

    day_ids: dict[int, Any] = {}
    pl_days = {d["day_index"]: d for d in pl["days"]}
    for day in entities["days"]:
        day_index = int(day["day_index"])
        day_id = seed_id("program_day", program_slug, str(day_index))
        day_ids[day_index] = day_id
        await session.execute(
            insert(ProgramDay)
            .values(
                id=day_id,
                program_id=program_id,
                day_index=day_index,
                sort_order=int(day.get("sort_order", day_index)),
            )
            .on_conflict_do_update(
                constraint="uq_program_days_program_day_index",
                set_={"sort_order": int(day.get("sort_order", day_index))},
            )
        )
        counts["program_days"] += 1
        day_tr = pl_days[day_index]
        await session.execute(
            insert(ProgramDayTranslation)
            .values(
                program_day_id=day_id,
                locale=LOCALE_PL,
                name=day_tr["name"],
            )
            .on_conflict_do_update(
                index_elements=["program_day_id", "locale"],
                set_={"name": day_tr["name"]},
            )
        )
        counts["translations"] += 1

    pl_exercises = {e["slug"]: e for e in pl["exercises"]}
    exercise_ids: dict[str, Any] = {}
    for ex in entities["exercises"]:
        slug = ex["slug"]
        eid = seed_id("exercise", slug)
        exercise_ids[slug] = eid
        await session.execute(
            insert(Exercise)
            .values(
                id=eid,
                user_id=None,
                program_id=program_id,
                slug=slug,
                name=None,
                kind="cc",
                exercise_type=ex["exercise_type"],
                description=None,
                active_metrics=ex["active_metrics"],
                schedule_kind=None,
                client_mutation_id=None,
                revision=1,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "program_id": program_id,
                    "exercise_type": ex["exercise_type"],
                    "active_metrics": ex["active_metrics"],
                },
            )
        )
        counts["exercises"] += 1
        et = pl_exercises[slug]
        await session.execute(
            insert(ExerciseTranslation)
            .values(
                exercise_id=eid,
                locale=LOCALE_PL,
                name=et["name"],
                description=et.get("description"),
            )
            .on_conflict_do_update(
                index_elements=["exercise_id", "locale"],
                set_={
                    "name": et["name"],
                    "description": et.get("description"),
                },
            )
        )
        counts["translations"] += 1

    rules_default = entities["step_rules_default"]
    steps_n = int(entities["steps_per_exercise"])
    pl_steps = {(s["exercise_slug"], int(s["step_number"])): s for s in pl["steps"]}
    for slug, eid in exercise_ids.items():
        for step_number in range(1, steps_n + 1):
            step_id = seed_id("exercise_step", slug, str(step_number))
            std = standards_by_key.get((slug, step_number))
            rules = rules_v2_from_standards(std) if std is not None else rules_default
            await session.execute(
                insert(ExerciseStep)
                .values(
                    id=step_id,
                    exercise_id=eid,
                    step_number=step_number,
                    name=None,
                    description=None,
                    rules=rules,
                    progression_schema_id=default_schema_id,
                    sort_order=step_number,
                )
                .on_conflict_do_update(
                    constraint="uq_exercise_steps_exercise_step",
                    set_={
                        "rules": rules,
                        "progression_schema_id": default_schema_id,
                        "sort_order": step_number,
                    },
                )
            )
            counts["exercise_steps"] += 1
            st = pl_steps[(slug, step_number)]
            await session.execute(
                insert(ExerciseStepTranslation)
                .values(
                    exercise_step_id=step_id,
                    locale=LOCALE_PL,
                    name=st["name"],
                    description=st["description"],
                    execution=st.get("execution") or "",
                    rationale=st.get("rationale") or "",
                    technique=st.get("technique") or "",
                    content_status=st.get("content_status", "draft"),
                )
                .on_conflict_do_update(
                    index_elements=["exercise_step_id", "locale"],
                    set_={
                        "name": st["name"],
                        "description": st["description"],
                        "execution": st.get("execution") or "",
                        "rationale": st.get("rationale") or "",
                        "technique": st.get("technique") or "",
                        "content_status": st.get("content_status", "draft"),
                    },
                )
            )
            counts["translations"] += 1

    for day in entities["days"]:
        day_id = day_ids[int(day["day_index"])]
        await session.execute(
            delete(ProgramDayExercise).where(ProgramDayExercise.program_day_id == day_id)
        )
        for order, ex_slug in enumerate(day["exercise_slugs"], start=1):
            link_id = seed_id("program_day_exercise", str(day["day_index"]), ex_slug)
            await session.execute(
                insert(ProgramDayExercise).values(
                    id=link_id,
                    program_day_id=day_id,
                    exercise_id=exercise_ids[ex_slug],
                    sort_order=order,
                )
            )

    for doc in legal_docs["documents"]:
        doc_id = seed_id("legal", doc["slug"], doc["version"])
        published = datetime.fromisoformat(doc["published_at"])
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        await session.execute(
            insert(LegalDocument)
            .values(
                id=doc_id,
                slug=doc["slug"],
                version=doc["version"],
                published_at=published,
            )
            .on_conflict_do_update(
                constraint="uq_legal_documents_slug_version",
                set_={"published_at": published},
            )
        )
        counts["legal_documents"] += 1

    for tr in legal_pl["translations"]:
        doc_id = seed_id("legal", tr["document_slug"], tr["document_version"])
        digest = legal_content_hash(tr["title"], tr["body"])
        await session.execute(
            insert(LegalDocumentTranslation)
            .values(
                document_id=doc_id,
                locale=LOCALE_PL,
                title=tr["title"],
                body=tr["body"],
                content_hash=digest,
            )
            .on_conflict_do_update(
                index_elements=["document_id", "locale"],
                set_={
                    "title": tr["title"],
                    "body": tr["body"],
                    "content_hash": digest,
                },
            )
        )
        counts["legal_translations"] += 1

    await session.commit()
    return counts


async def run_seed() -> dict[str, int]:
    engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            return await seed_all(session)
    finally:
        await engine.dispose()
