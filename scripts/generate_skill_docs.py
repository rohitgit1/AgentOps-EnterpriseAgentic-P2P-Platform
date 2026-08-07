"""Generate /skills/<name>/SKILL.md from the live skill descriptors.

Keeping the markdown generated means the documented contract and the executing
code can never drift apart. Run after changing any skill:

    python scripts/generate_skill_docs.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.registry import list_agents  # noqa: E402
from app.skills import catalog  # noqa: E402

TEMPLATE = """# {title} Skill

> Generated from `backend/app/skills/{name}.py`. Do not edit by hand —
> run `python scripts/generate_skill_docs.py` instead.

## Purpose
{purpose}

## Inputs
{inputs}

## Output
```json
{{
{output}
}}
```

## Success Criteria
{success}

## Failure Handling
{failure}

## Used By
{used_by}

## Human-in-the-loop contract
This skill performs analysis only. It cannot write to a system of record.
Whatever it returns becomes evidence attached to an agent proposal, and that
proposal is executed only after a qualified human approves it at a checkpoint.
"""


def main() -> None:
    agents = list_agents()
    out_root = ROOT / "skills"
    out_root.mkdir(exist_ok=True)
    written = []

    for skill in catalog():
        users = [a.name for a in agents if skill["name"] in (a.skills or [])]
        body = TEMPLATE.format(
            title=skill["title"],
            name=skill["name"],
            purpose=skill["purpose"],
            inputs="\n".join(f"- {i}" for i in skill.get("inputs", [])) or "- (none)",
            output=",\n".join(f'  "{o}"' for o in skill.get("output", [])),
            success=skill.get("success_criteria", ""),
            failure=skill.get("failure_handling", ""),
            used_by="\n".join(f"- {u}" for u in (users or skill.get("used_by", []))) or "- (unassigned)",
        )
        target = out_root / skill["name"]
        target.mkdir(exist_ok=True)
        (target / "SKILL.md").write_text(body)
        written.append(skill["name"])

    index = ["# Shared Skills Framework", "",
             "Reusable capabilities the agents compose. Each folder holds the contract for one",
             "skill; the implementation lives in `backend/app/skills/`.", "",
             "| Skill | Purpose | Used by |", "|---|---|---|"]
    for skill in catalog():
        users = [a.name for a in agents if skill["name"] in (a.skills or [])]
        index.append(
            f"| [`{skill['name']}`](./{skill['name']}/SKILL.md) | {skill['purpose']} | "
            f"{', '.join(users) or '—'} |"
        )
    index += ["", "Skills analyse and return evidence. They never mutate the system of record —",
              "only an approved human checkpoint can do that.", ""]
    (out_root / "README.md").write_text("\n".join(index))

    print(f"Wrote {len(written)} SKILL.md files + index to {out_root}")


if __name__ == "__main__":
    main()
