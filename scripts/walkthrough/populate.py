"""Drive the demo to a realistic state before capturing screenshots.

Approving is what fills the business tables, so a freshly-swept demo shows
empty states on half the screens. This runs the agents, then approves their
proposals as the persona whose authority actually covers each action — which is
the platform's own loop, not a shortcut around it.
"""
import json, sys, time, urllib.request

BASE = "http://127.0.0.1:8000/api"

def call(method, path, body=None, user=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if user: req.add_header("X-User-Id", user)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data, timeout=180) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_detail": e.read().decode()[:180]}

personas = {p["role"]: p["id"] for p in call("GET", "/auth/personas")}
ADMIN = personas["admin"]
# Highest authority first — decide() enforces the ladder, so a fallback chain
# means each task is decided by the first persona actually permitted.
CHAIN = [personas[r] for r in ("admin", "cfo", "controller", "ap_manager",
                               "procurement", "treasury", "ap_clerk") if r in personas]

def artifacts():
    r = call("GET", "/artifacts", user=ADMIN)
    rows = r.get("items", []) if isinstance(r, dict) else r
    return {a["filename"]: a["id"] for a in rows if a.get("direction") == "input"}

def approve_all(label, limit=400):
    """Approve every pending checkpoint, trying personas in authority order."""
    tasks = call("GET", "/hitl/tasks?status=pending&limit=500", user=ADMIN)
    tasks = tasks if isinstance(tasks, list) else tasks.get("items", [])
    ok = failed = 0
    for t in tasks[:limit]:
        for uid in CHAIN:
            r = call("POST", f"/hitl/tasks/{t['id']}/decide",
                     {"decision": "approve", "notes": "Reviewed for the walkthrough capture."}, uid)
            if "_error" not in r:
                ok += 1; break
        else:
            failed += 1
    print(f"  {label}: approved {ok}, could not decide {failed}")
    return ok

print("1. fleet sweep")
print("  ", call("POST", "/orchestrator/sweep", {}, ADMIN))
approve_all("after sweep")

print("2. procurement agents with their sample attachments")
art = artifacts()
runs = [
    ("spend_analytics",           ["spend-extract-q4.csv"], {}),
    ("supplier_risk_compliance",  ["credit-report.csv", "otif-performance.csv"], {}),
    ("contract_lifecycle",        ["trident-msa-draft.md"], {}),
    ("tail_spend",                ["spend-extract-q4.csv", "catalog.csv"], {}),
    ("procurement_command_center", [], {}),
    ("sourcing_rfp",              ["requirements-freight-fy27.md"],
     {"category": "Freight & Logistics", "budget": 850000,
      "title": "Regional freight FY27"}),
]
for key, files, extra in runs:
    ids = [art[f] for f in files if f in art]
    body = {"attachment_ids": ids, **extra} if ids else dict(extra)
    r = call("POST", f"/agents/{key}/run", body, ADMIN)
    print(f"   {key}: {r.get('status', r.get('_error'))} · "
          f"{len(r.get('checkpoints') or r.get('tasks') or [])} checkpoint(s)")

approve_all("after procurement runs")

print("3. score the issued sourcing event")
events = call("GET", "/sourcing-events", user=ADMIN)
issued = [e for e in (events if isinstance(events, list) else []) if e.get("status") == "issued"]
for e in issued[:2]:
    bids = art.get("bids-SRC-9002.csv")
    body = {"event_id": e["id"], **({"attachment_ids": [bids]} if bids else {})}
    r = call("POST", "/agents/sourcing_rfp/run", body, ADMIN)
    print(f"   scored {e.get('event_number')}: {r.get('status', r.get('_error'))}")
approve_all("after bid scoring")

print("4. second sweep so the P2P pipeline advances")
print("  ", call("POST", "/orchestrator/sweep", {}, ADMIN))
approve_all("after second sweep", limit=300)

print("5. third sweep — leaves a realistic queue of open checkpoints")
print("  ", call("POST", "/orchestrator/sweep", {}, ADMIN))

d = call("GET", "/data-model", user=ADMIN)
counts = {t["name"]: t["row_count"] for dom in d["domains"] for t in dom["tables"]}
print("\nrow counts now:")
for t in ["exceptions", "payments", "approvals", "savings_opportunities",
          "risk_assessments", "contract_drafts", "tail_spend_findings",
          "sourcing_events", "sourcing_bids", "artifacts", "human_tasks",
          "agent_executions", "audit_logs"]:
    print(f"   {t:24} {counts.get(t, 0)}")
