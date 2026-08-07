"""Generate /agents/<key>/AGENT.md — a complete build specification per agent.

The goal is reconstructability: someone with only `agents/<key>/AGENT.md` should
be able to rebuild that agent from scratch and get the same behaviour, without
reading the original source.

Everything mechanical is extracted from the code itself:

  * identity, governance defaults, I/O contract and prompt  — from the class
  * lifecycle steps                                          — from `plan()`
  * proposal catalogue, payload keys, diff fields            — AST of the module
  * policy keys consulted                                    — AST of the module
  * tables read / written, executor behaviour                — AST + the HITL
                                                               action registry
  * reversibility and minimum approver per action            — from `enums.py`

What cannot be extracted — the *reasoning*: branch conditions, thresholds,
confidence formulas, escalation triggers — is hand-written once per agent in
`scripts/agent_build_notes.py` and merged in here. That file is the only part a
maintainer edits when an agent's logic changes.

Run after changing any agent:

    python scripts/generate_agent_specs.py
"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.registry import list_agents, suites  # noqa: E402
from app.api.explain import WORKED_EXAMPLES  # noqa: E402
from app.database import Base  # noqa: E402
from app.enums import (  # noqa: E402
    ACTION_LABELS,
    ActionKind,
    ACTION_MIN_ROLE,
    AUTONOMY_LABELS,
    IRREVERSIBLE_ACTIONS,
    ROLE_LABELS,
    SUITE_BLURBS,
    SUITE_LABELS,
)
from app.services import hitl  # noqa: E402
from app.services.policy import DEFAULT_POLICIES  # noqa: E402
from app.skills import catalog as skills_catalog  # noqa: E402

from agent_build_notes import BUILD_NOTES  # noqa: E402

def _dual_threshold() -> float:
    for rule in DEFAULT_POLICIES:
        if rule.get("key") == "hitl.dual_approval_above":
            return float(rule.get("number_value") or rule.get("value") or 100_000)
    return 100_000.0


# Model class name -> table name, so "imports Invoice" becomes "reads invoices".
TABLE_BY_MODEL = {
    mapper.class_.__name__: mapper.class_.__tablename__
    for mapper in Base.registry.mappers
}


# ==========================================================================
# Static analysis
# ==========================================================================
def _literal(node: ast.AST) -> str | None:
    """Render a node as source-ish text when it is simple enough to be useful."""
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Attribute):
        parts = []
        cur: ast.AST = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


def _action_value(dotted: str) -> str:
    """`ActionKind.CREATE_EXCEPTION` -> `create_exception`, so specs and code agree."""
    attr = dotted.rsplit(".", 1)[-1]
    return str(getattr(ActionKind, attr, attr))


def _dict_keys(node: ast.AST) -> list[str]:
    if not isinstance(node, ast.Dict):
        return []
    keys = []
    for key in node.keys:
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            keys.append(key.value)
    return keys


def _proposals(tree: ast.AST) -> list[dict]:
    """Every ProposedAction the agent constructs, with its payload shape."""
    found: list[dict] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "ProposedAction"):
            continue
        entry: dict = {"action": None, "title": None, "payload_keys": [],
                       "diff_fields": [], "confidence": None, "due_in_hours": None,
                       "financial_impact": None, "alternatives": False,
                       "artifacts": False, "extra_flags": False}
        for kw in node.keywords:
            if kw.arg == "action_kind":
                entry["action"] = _action_value(_literal(kw.value) or "")
            elif kw.arg == "title":
                entry["title"] = _literal(kw.value)
            elif kw.arg == "payload":
                entry["payload_keys"] = _dict_keys(kw.value)
            elif kw.arg == "diff_preview" and isinstance(kw.value, ast.List):
                for element in kw.value.elts:
                    for key, value in zip(getattr(element, "keys", []),
                                          getattr(element, "values", [])):
                        if (isinstance(key, ast.Constant) and key.value == "field"
                                and isinstance(value, ast.Constant)):
                            entry["diff_fields"].append(value.value)
            elif kw.arg == "confidence":
                entry["confidence"] = _literal(kw.value)
            elif kw.arg == "due_in_hours":
                entry["due_in_hours"] = _literal(kw.value)
            elif kw.arg == "financial_impact_usd":
                entry["financial_impact"] = _literal(kw.value)
            elif kw.arg == "alternatives":
                entry["alternatives"] = True
            elif kw.arg == "artifact_ids":
                entry["artifacts"] = True
            elif kw.arg == "extra_flags":
                entry["extra_flags"] = True
        found.append(entry)

    # One agent may raise the same action on several branches; merge them so the
    # spec shows the union of the payload it must be able to carry.
    merged: dict[str, dict] = {}
    for entry in found:
        key = entry["action"] or "?"
        if key not in merged:
            merged[key] = {**entry, "titles": [entry["title"]] if entry["title"] else [],
                           "branches": 1}
            continue
        target = merged[key]
        target["branches"] += 1
        if entry["title"]:
            target["titles"].append(entry["title"])
        for field in ("payload_keys", "diff_fields"):
            for value in entry[field]:
                if value not in target[field]:
                    target[field].append(value)
        for flag in ("alternatives", "artifacts", "extra_flags"):
            target[flag] = target[flag] or entry[flag]
    return list(merged.values())


def _policy_keys(tree: ast.AST) -> list[tuple[str, str]]:
    """Policy-as-code keys the agent reads, with the fallback it uses."""
    keys: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in {"number", "flag", "text", "value"}:
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        name = node.args[0].value
        if not isinstance(name, str) or "." not in name:
            continue
        default = _literal(node.args[1]) if len(node.args) > 1 else "—"
        pair = (name, default or "—")
        if pair not in keys:
            keys.append(pair)
    return sorted(keys)


def _imported(tree: ast.AST, module: str) -> list[str]:
    """Names imported from `..module` — relative imports arrive without the dots."""
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[-1] == module:
            names += [alias.name for alias in node.names]
    return sorted(set(names))


def _written_tables(fn) -> list[str]:
    """Tables an executor actually writes.

    Tracks local names bound to a model — by construction (`Payment(...)`) or by
    lookup (`db.get(Invoice, ...)`) — then counts any attribute assignment onto
    one of those names as a write. Constructing a model is always a write; a
    lookup only counts once something is assigned to it.
    """
    try:
        source = inspect.getsource(fn)
    except (OSError, TypeError):  # pragma: no cover - defensive
        return []
    tree = ast.parse(source.lstrip())

    hits: set[str] = set()
    # Executors bind rows through helpers too (`invoice = _invoice(...)`), so a
    # local whose name is a model name in lower case counts as that model.
    bound: dict[str, str] = {model.lower(): table
                             for model, table in TABLE_BY_MODEL.items()}

    def model_of(node: ast.AST) -> str | None:
        """The table a call yields, for `Model(...)` and `db.get(Model, ...)`."""
        if not isinstance(node, ast.Call):
            return None
        if isinstance(node.func, ast.Name):
            if node.func.id == "notify":
                hits.add("notifications")
            return TABLE_BY_MODEL.get(node.func.id)
        if (isinstance(node.func, ast.Attribute) and node.func.attr == "get"
                and node.args and isinstance(node.args[0], ast.Name)):
            return TABLE_BY_MODEL.get(node.args[0].id)
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                table = TABLE_BY_MODEL.get(node.func.id)
                if table:
                    hits.add(table)          # constructing a row is a write
                if node.func.id == "notify":
                    hits.add("notifications")
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            table = model_of(value) if value is not None else None
            if table:
                for target in targets:
                    if isinstance(target, ast.Name):
                        bound[target.id] = table
            # x.attr = ... on a tracked name is a write to that table
            for target in targets:
                if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                        and target.value.id in bound):
                    hits.add(bound[target.value.id])
        if isinstance(node, ast.AugAssign):
            target = node.target
            if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                    and target.value.id in bound):
                hits.add(bound[target.value.id])

    return sorted(hits)


# ==========================================================================
# Rendering
# ==========================================================================
def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_None._"
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def _bullets(items, empty: str = "_None._") -> str:
    items = [i for i in (items or []) if i]
    return "\n".join(f"- {i}" for i in items) if items else empty


def render(agent, notes: dict) -> str:
    module = sys.modules[type(agent).__module__]
    source_path = Path(inspect.getfile(type(agent)))
    tree = ast.parse(source_path.read_text())
    rel_source = source_path.relative_to(ROOT).as_posix()

    described = agent.describe()
    config = agent.default_config()
    proposals = _proposals(tree)
    policy_keys = _policy_keys(tree)
    models = _imported(tree, "models")
    skill_modules = _imported(tree, "skills")
    skills_by_name = {s["name"]: s for s in skills_catalog()}
    example = WORKED_EXAMPLES.get(agent.key)

    try:
        steps = agent.plan(None, {})  # every plan() is a static declaration
    except Exception:  # pragma: no cover - defensive
        steps = []

    out: list[str] = []
    add = out.append

    # ---- header ----------------------------------------------------------
    add(f"# {agent.name}")
    add("")
    add(f"> **Build specification.** Generated from `{rel_source}` by")
    add("> `python scripts/generate_agent_specs.py`. Do not edit by hand — change the")
    add("> agent, or its entry in `scripts/agent_build_notes.py`, and regenerate.")
    add("")
    add(f"`{agent.key}` · {SUITE_LABELS.get(str(agent.suite), agent.suite)} · "
        f"class `{type(agent).__name__}`")
    add("")
    add(f"**Role.** {agent.role}")
    add("")
    add(f"**Mission.** {agent.mission}")
    add("")
    if (module.__doc__ or "").strip():
        add("**Module intent.**")
        add("")
        add("```")
        add((module.__doc__ or "").strip())
        add("```")
        add("")

    # ---- 1. contract -----------------------------------------------------
    add("---")
    add("")
    add("## 1 · What it consumes and what it returns")
    add("")
    add("### Inputs")
    add("")
    add(_table(
        ["Name", "Kind", "Required", "Formats", "Description", "Example"],
        [[i.name, i.kind, "yes" if i.required else "no",
          ", ".join(f"`.{f}`" for f in i.formats) or "—",
          i.description, f"`{i.example}`" if i.example else "—"]
         for i in agent.inputs],
    ))
    add("")
    add("### Outputs")
    add("")
    add(_table(
        ["Name", "Kind", "Formats", "Description", "Example"],
        [[o.name, o.kind, ", ".join(f"`.{f}`" for f in o.formats) or "—",
          o.description, f"`{o.example}`" if o.example else "—"]
         for o in agent.outputs],
    ))
    add("")
    add(f"Accepts attachments: **{'yes' if described['accepts_attachments'] else 'no'}** · "
        f"Produces downloadable files: **{'yes' if described['produces_artifacts'] else 'no'}**")
    add("")
    if described["accepts_attachments"]:
        add("Attachments arrive already parsed. `run()` resolves `context[\"attachment_ids\"]`")
        add("through `artifacts.load_for_agent()` and puts the result in")
        add("`context[\"attachments\"]` — CSV/TSV as typed rows plus a field list, JSON as")
        add("records, Markdown/text as full text, PDF as its embedded text layer. An")
        add("unreadable file degrades to raw text with a stated reason rather than raising,")
        add("so the agent can report *\"I could not read this\"* instead of crashing.")
        add("")

    # ---- 2. governance ---------------------------------------------------
    add("---")
    add("")
    add("## 2 · Governance envelope")
    add("")
    add(_table(["Setting", "Value", "Meaning"], [
        ["`default_stage`", f"`{config['agent_key'] and str(agent.default_stage)}`",
         "Workflow stage its checkpoints are filed under"],
        ["`default_autonomy`", f"`{config['autonomy_level']}` — "
         f"{AUTONOMY_LABELS.get(config['autonomy_level'], '')}",
         "Seeded into `agent_configs`; editable in the Agent Control Room"],
        ["`default_confidence_threshold`", f"`{config['confidence_threshold']}`",
         "Below this the proposal must reach a human regardless of anything else"],
        ["`max_auto_amount_usd`", f"`{config['max_auto_amount_usd']:,.0f}`",
         "Financial ceiling for auto-execution; `0` means never"],
        ["`escalation_role`", f"`{config['escalation_role']}` — "
         f"{ROLE_LABELS.get(config['escalation_role'], '')}",
         "Who this agent escalates to"],
    ]))
    add("")
    add("The global HITL switch overrides all of it. While")
    add("`enforce_human_in_the_loop` is on — the default — no proposal from this agent")
    add("executes without an explicit human decision, whatever its autonomy level says.")
    add("")

    # ---- 3. actions ------------------------------------------------------
    add("---")
    add("")
    add("## 3 · Actions it may propose")
    add("")
    rows = []
    for action_kind in agent.allowed_actions:
        key = str(action_kind)
        handler = hitl._HANDLERS.get(key)
        rows.append([
            f"`{key}`",
            ACTION_LABELS.get(key, key),
            "**no — irreversible**" if key in IRREVERSIBLE_ACTIONS else "yes",
            ROLE_LABELS.get(ACTION_MIN_ROLE.get(key, ""), ACTION_MIN_ROLE.get(key, "—")),
            f"`{handler.__name__}`" if handler else "**missing**",
        ])
    add(_table(["Action", "Label", "Reversible", "Minimum approver", "Executor"], rows))
    add("")
    add("Authority escalates with value on top of the minimum above: at or above")
    add("$50,000 a Controller is required, at or above $250,000 the CFO, and above")
    add(f"${_dual_threshold():,.0f} two distinct approvers are required "
        "(`hitl.dual_approval_above`, editable in Governance).")
    add("")

    if proposals:
        add("### Proposal payloads")
        add("")
        add("The payload each proposal carries. The executor reads exactly these keys, so")
        add("a rebuild must produce them under the same names.")
        add("")
        for entry in proposals:
            action_key = entry["action"] or "?"
            add(f"#### `{action_key}`")
            add("")
            titles = list(dict.fromkeys(t for t in entry.get("titles", []) if t))
            count = entry["branches"]
            where = "on 1 branch" if count == 1 else f"on {count} branches"
            if titles:
                add(f"Raised {where}, e.g. " + "; ".join(f"*{t}*" for t in titles) + ".")
            else:
                add(f"Raised {where}.")
            add("")
            if entry["payload_keys"]:
                add("```json")
                add("{")
                add(",\n".join(f'  "{k}": …' for k in entry["payload_keys"]))
                add("}")
                add("```")
            else:
                add("_Empty payload — the executor works from `task.entity_id`._")
            add("")
            details = []
            if entry["diff_fields"]:
                details.append("Diff preview: "
                               + ", ".join(f"`{f}`" for f in entry["diff_fields"]))
            if entry["confidence"]:
                details.append(f"Confidence: `{entry['confidence']}`")
            if entry["due_in_hours"]:
                details.append(f"Due in: `{entry['due_in_hours']}` hours")
            if entry["alternatives"]:
                details.append("Carries priced alternatives for the reviewer")
            if entry["artifacts"]:
                details.append("Releases linked draft deliverables on approval")
            if entry["extra_flags"]:
                details.append("Sets extra flags the policy engine reads")
            if details:
                add(_bullets(details))
                add("")

        add("### What approval actually changes")
        add("")
        write_rows = []
        for action_kind in agent.allowed_actions:
            key = str(action_kind)
            handler = hitl._HANDLERS.get(key)
            if handler is None:
                continue
            tables = _written_tables(handler)
            write_rows.append([f"`{key}`",
                               ", ".join(f"`{t}`" for t in tables) or "—"])
        add(_table(["Action", "Tables the executor touches"], write_rows))
        add("")
        add("Every executor also appends to `audit_logs` (hash-chained) and")
        add("`workflow_events`. Nothing above happens before approval.")
        add("")

    # ---- 4. lifecycle ----------------------------------------------------
    add("---")
    add("")
    add("## 4 · Lifecycle")
    add("")
    add("`plan() → gather() → decide()` inside the base class's")
    add("`plan / execute / observe / reason / escalate / report` run loop.")
    add("")
    add("### Declared plan")
    add("")
    add(_table(["#", "Action", "Tool", "Why"],
               [[s.step, s.action, f"`{s.tool}`", s.rationale] for s in steps]))
    add("")
    if notes.get("gather"):
        add("### `gather()` — evidence collection")
        add("")
        add(notes["gather"].strip())
        add("")
    if notes.get("decide"):
        add("### `decide()` — the reasoning")
        add("")
        add(notes["decide"].strip())
        add("")
    if notes.get("thresholds"):
        add("### Thresholds and formulas")
        add("")
        add(_table(["Quantity", "Value", "Where it comes from"],
                   [list(row) for row in notes["thresholds"]]))
        add("")
    if notes.get("escalation"):
        add("### Escalation")
        add("")
        add(notes["escalation"].strip())
        add("")
    if notes.get("handoff"):
        add("### Handoff")
        add("")
        add(notes["handoff"].strip())
        add("")

    # ---- 5. dependencies -------------------------------------------------
    add("---")
    add("")
    add("## 5 · Dependencies")
    add("")
    add("### Skills")
    add("")
    skill_rows = []
    for name in agent.skills:
        entry = skills_by_name.get(name)
        skill_rows.append([
            f"`{name}`",
            entry["purpose"] if entry else "_Declared by the agent; not in the shared catalogue._",
            f"[contract](../../skills/{name}/SKILL.md)" if entry else "—",
        ])
    add(_table(["Skill", "Purpose", "Contract"], skill_rows))
    add("")
    if skill_modules:
        add(f"Imported skill modules: {', '.join(f'`{s}`' for s in skill_modules)}")
        add("")
    add("### Data it reads")
    add("")
    read_tables = sorted({TABLE_BY_MODEL[m] for m in models if m in TABLE_BY_MODEL})
    add(_bullets([f"`{t}`" for t in read_tables], "_Reads no tables directly._"))
    add("")
    if policy_keys:
        add("### Policy-as-code keys it consults")
        add("")
        add(_table(["Key", "Fallback"],
                   [[f"`{k}`", f"`{d}`"] for k, d in policy_keys]))
        add("")
        add("These are rows in `policy_rules`, read on every run. Changing governance is a")
        add("data change, not a code change.")
        add("")
    add("### External systems")
    add("")
    add(_bullets([f"{t}" for t in agent.tools]))
    add("")

    # ---- 6. worked example ----------------------------------------------
    if example:
        add("---")
        add("")
        add("## 6 · Worked example")
        add("")
        add(f"**Scenario.** {example['scenario']}")
        add("")
        add(f"**Given.** {example['given']}")
        add("")
        add("**It does:**")
        add("")
        add("\n".join(f"{i}. {s}" for i, s in enumerate(example["steps"], start=1)))
        add("")
        add(f"**Produces.** {example['produces']}")
        add("")
        add(f"**Decided by.** {example['decided_by']}")
        add("")

    # ---- 7. prompt -------------------------------------------------------
    add("---")
    add("")
    add("## 7 · Operating brief")
    add("")
    add("Generated by `BaseAgent.prompt_template()` from the identity above. Used")
    add("verbatim when a live LLM provider is configured; the deterministic reasoner")
    add("narrates from the same evidence when one is not.")
    add("")
    add("```text")
    add(described["prompt"].strip())
    add("```")
    add("")

    # ---- 8. rebuild ------------------------------------------------------
    add("---")
    add("")
    add("## 8 · Rebuild checklist")
    add("")
    add(f"1. Subclass `BaseAgent` in `backend/app/agents/{source_path.stem}.py` with")
    add(f"   `key = \"{agent.key}\"` and the identity, governance and `allowed_actions`")
    add("   from sections 2 and 3.")
    add("2. Declare `inputs` and `outputs` as `IOSpec` objects matching section 1 — these")
    add("   drive the Agent I/O Catalogue and the Academy, and are the contract an")
    add("   evaluator reads before running anything.")
    add("3. Implement `plan()` returning the `PlanStep` list in section 4, verbatim. It is")
    add("   a static declaration and is read without a live context.")
    add("4. Implement `gather()` per section 4, returning one `Observation` per tool.")
    add("   Persist anything `decide()` needs on `context`, never on `self` — agents are")
    add("   singletons and a run must not leak into the next.")
    add("5. Implement `decide()` per section 4, returning an `AgentDecision` whose")
    add("   `proposals` carry exactly the payload keys in section 3.")
    if agent.allowed_actions:
        add("6. Confirm every action has an executor registered with `@action(...)` in")
        add("   `backend/app/services/hitl.py`. An agent that proposes an unexecutable")
        add("   action fails `test_every_procurement_action_has_an_executor`.")
        add("7. Register the class in `backend/app/agents/registry.py`.")
    else:
        add("6. Register the class in `backend/app/agents/registry.py`.")
    add("")
    add("**Invariants a rebuild must not break:**")
    add("")
    add("- `decide()` returns proposals. It must never write to a business table, call an")
    add("  executor, or mutate an ORM object it did not create as a draft artifact.")
    add("- Confidence is a real number the agent stands behind, not a constant. The")
    add("  policy engine gates on it.")
    add("- Every claim in `evidence` cites the observation it came from, so a reviewer")
    add("  months later can reconstruct the decision.")
    add("- Financial impact is the amount actually at risk. It drives role escalation and")
    add("  the dual-approval threshold, so an inflated figure blocks work and a deflated")
    add("  one under-reviews it.")
    add("")

    return "\n".join(out) + "\n"


# ==========================================================================
# Index
# ==========================================================================
def render_index(grouped) -> str:
    out = [
        "# Agent Build Specifications",
        "",
        "One folder per agent. Each `AGENT.md` is a complete build specification —",
        "identity, governance envelope, I/O contract, proposal payloads, lifecycle,",
        "reasoning, thresholds, dependencies and a rebuild checklist — sufficient to",
        "reconstruct that agent from scratch without reading the original source.",
        "",
        "Generated by `python scripts/generate_agent_specs.py`. The mechanical content",
        "comes from the code; the reasoning notes come from `scripts/agent_build_notes.py`.",
        "",
        "See [`docs/SPECIFICATION.md`](../docs/SPECIFICATION.md) for the platform these",
        "agents run on, and [`skills/`](../skills/README.md) for the shared capabilities",
        "they compose.",
        "",
    ]
    for suite_key, agents in grouped.items():
        out += [f"## {SUITE_LABELS.get(suite_key, suite_key)}", "",
                SUITE_BLURBS.get(suite_key, ""), "",
                "| Agent | Role | Proposes | Autonomy |", "|---|---|---|---|"]
        for agent in agents:
            actions = ", ".join(f"`{a}`" for a in agent.allowed_actions) or "—"
            out.append(
                f"| [{agent.name}](./{agent.key}/AGENT.md) | {agent.role} | {actions} | "
                f"{AUTONOMY_LABELS.get(str(agent.default_autonomy), '')} |"
            )
        out.append("")
    out += [
        "---",
        "",
        "## The rule these specifications exist to preserve",
        "",
        "An agent returns proposals, never mutations. There is no code path from an agent",
        "to a business table. Its only output is a `HumanTask` holding the payload that",
        "*would* be applied, and that payload reaches a system of record only when someone",
        "with the required authority approves the checkpoint.",
        "",
        "Any rebuild that breaks this is not a rebuild of this agent.",
        "",
    ]
    return "\n".join(out)


def main() -> None:
    out_root = ROOT / "agents"
    out_root.mkdir(exist_ok=True)

    missing = [a.key for a in list_agents() if a.key not in BUILD_NOTES]
    if missing:
        raise SystemExit(
            f"No build notes for: {', '.join(missing)}. Add them to "
            f"scripts/agent_build_notes.py — a spec without the reasoning is not a "
            f"spec someone can rebuild from."
        )

    for agent in list_agents():
        target = out_root / agent.key
        target.mkdir(exist_ok=True)
        (target / "AGENT.md").write_text(render(agent, BUILD_NOTES[agent.key]))

    (out_root / "README.md").write_text(render_index(suites()))
    print(f"Wrote {len(list_agents())} AGENT.md files + index to {out_root}")


if __name__ == "__main__":
    main()
