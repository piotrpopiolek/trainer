"""Parse Aneks B from the plan and merge into pl-PL catalog.json."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = Path(r"c:\Users\piotr\.cursor\plans\progi_i_content_cc_6a3cd8b1.plan.md")
CATALOG = ROOT / "backend" / "seed" / "cc" / "pl-PL" / "catalog.json"

SECTION_ORDER = [
    "push_ups",
    "squats",
    "pull_ups",
    "leg_raises",
    "bridges",
    "handstand_push_ups",
]


def parse_annex_b(text: str) -> dict[tuple[str, int], dict[str, str]]:
    start = text.index("## Aneks B")
    end = text.index("## Poza zakresem")
    body = text[start:end]
    out: dict[tuple[str, int], dict[str, str]] = {}
    current_slug: str | None = None
    current_n: int | None = None
    current_name: str | None = None
    fields: dict[str, str] = {}

    def flush() -> None:
        nonlocal current_n, current_name, fields
        if current_slug is None or current_n is None:
            return
        need = ("Lead", "Wykonanie", "Rentgen", "Doskonalenie")
        missing = [k for k in need if k not in fields]
        if missing:
            raise SystemExit(f"missing {missing} for {current_slug}#{current_n}")
        out[(current_slug, current_n)] = {
            "name": current_name or "",
            "description": fields["Lead"],
            "execution": fields["Wykonanie"],
            "rationale": fields["Rentgen"],
            "technique": fields["Doskonalenie"],
        }
        current_n = None
        current_name = None
        fields = {}

    for line in body.splitlines():
        m_sec = re.match(r"^### (\w+)\s*$", line)
        if m_sec:
            flush()
            current_slug = m_sec.group(1)
            continue
        m_step = re.match(r"^\*\*#(\d+)\s+(.+?)\*\*\s*$", line)
        if m_step:
            flush()
            current_n = int(m_step.group(1))
            current_name = m_step.group(2).strip()
            continue
        m_field = re.match(
            r"^- (Lead|Wykonanie|Rentgen|Doskonalenie):\s*(.+?)\s*$",
            line,
        )
        if m_field and current_slug and current_n is not None:
            fields[m_field.group(1)] = m_field.group(2).rstrip()
    flush()
    return out


def main() -> None:
    annex = parse_annex_b(PLAN.read_text(encoding="utf-8"))
    assert len(annex) == 60, len(annex)
    for slug in SECTION_ORDER:
        for n in range(1, 11):
            assert (slug, n) in annex, (slug, n)

    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    cat["catalog_version"] = max(int(cat.get("catalog_version", 1)), 4)
    by_key = {(s["exercise_slug"], int(s["step_number"])): s for s in cat["steps"]}
    for (slug, n), fields in annex.items():
        step = by_key[(slug, n)]
        # Keep Trainer names already in catalog unless annex name is set
        if fields["name"]:
            step["name"] = fields["name"]
        step["description"] = fields["description"]
        step["execution"] = fields["execution"]
        step["rationale"] = fields["rationale"]
        step["technique"] = fields["technique"]
        step["content_status"] = "ready"

    CATALOG.write_text(
        json.dumps(cat, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"updated {CATALOG} catalog_version={cat['catalog_version']} steps=60")


if __name__ == "__main__":
    main()
