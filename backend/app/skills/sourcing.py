"""Sourcing skills — RFP orchestration, supplier discovery, bid evaluation, award."""
from __future__ import annotations

import re
from datetime import date, timedelta

SKILL = {
    "name": "rfp_orchestration",
    "title": "RFP Orchestration",
    "purpose": "Create and manage sourcing events end to end, from requirements to award.",
    "inputs": ["business requirements", "budget", "category strategy", "compliance rules"],
    "output": ["rfp_package", "supplier_shortlist", "bid_scorecard", "award_recommendation"],
    "success_criteria": "Sourcing cycle reduced >50%; bid participation >80%.",
    "failure_handling": "Never issues an RFP or awards business itself — both require sign-off.",
    "used_by": ["sourcing_rfp"],
}

DISCOVERY = {
    "name": "supplier_discovery",
    "title": "Supplier Discovery",
    "purpose": "Shortlist qualified suppliers for a category from vendor master and market signals.",
    "inputs": ["category", "budget", "compliance rules", "incumbent suppliers"],
    "output": ["shortlist", "qualification_flags", "coverage_rationale"],
    "success_criteria": "Every shortlisted supplier passes compliance pre-screen.",
    "failure_handling": "Blocked or sanctioned suppliers are excluded with the reason stated.",
    "used_by": ["sourcing_rfp"],
}

BID_EVALUATION = {
    "name": "bid_evaluation",
    "title": "Bid Evaluation",
    "purpose": "Score bids on commercial, technical and risk dimensions against declared weights.",
    "inputs": ["bids", "evaluation weights", "budget", "supplier risk"],
    "output": ["scored_bids", "ranking", "award_recommendation", "savings_estimate"],
    "success_criteria": "Award recommendation is reproducible from the published weights.",
    "failure_handling": "A tie or a sub-threshold winner escalates rather than picking arbitrarily.",
    "used_by": ["sourcing_rfp"],
}

DEFAULT_WEIGHTS = {"commercial": 0.45, "technical": 0.35, "risk": 0.20}


# --------------------------------------------------------------------------
# Requirement analysis
# --------------------------------------------------------------------------
_REQ_PATTERNS = {
    "volume": r"(\d[\d,]*)\s*(?:units|licences|licenses|seats|tonnes|tons|hours|pallets)",
    "term": r"(\d+)[\s-]*(?:month|year)",
    "budget": r"(?:budget|not to exceed|nte|cap)\D{0,20}([$€£]?\s?[\d,]+(?:\.\d{2})?)",
    "service_level": r"(\d{2,3}(?:\.\d+)?)\s*%\s*(?:sla|uptime|availability|otif|on-time)",
}


def analyze_requirements(text: str) -> dict:
    """Pull structured sourcing parameters out of a free-text requirements brief."""
    flat = " ".join((text or "").split())
    found: dict = {}
    for name, pattern in _REQ_PATTERNS.items():
        match = re.search(pattern, flat, re.IGNORECASE)
        if match:
            raw = match.group(1)
            found[name] = (
                float(re.sub(r"[^\d.]", "", raw)) if name in {"volume", "budget", "service_level"}
                else int(raw)
            )

    # Requirement bullets are the substance of the RFP scope section.
    bullets = [
        line.strip(" -•*\t")
        for line in (text or "").splitlines()
        if line.strip().startswith(("-", "•", "*")) and len(line.strip()) > 4
    ]
    missing = [k for k in ("volume", "term", "budget") if k not in found]
    completeness = round(1 - len(missing) / 3, 3)

    return {
        "parameters": found,
        "requirements": bullets,
        "requirement_count": len(bullets),
        "missing_parameters": missing,
        "completeness": completeness,
        "requires_human_review": completeness < 0.67 or not bullets,
    }


# --------------------------------------------------------------------------
# Supplier discovery
# --------------------------------------------------------------------------
def shortlist_suppliers(candidates: list[dict], *, category: str, limit: int = 5) -> dict:
    """Rank vendor-master candidates for a category. Compliance is a gate, not a weight."""
    scored, excluded = [], []
    category_l = (category or "").lower()

    for supplier in candidates:
        reasons = []
        if supplier.get("on_hold"):
            excluded.append({**supplier, "reason": "Supplier is blocked in vendor master."})
            continue
        if supplier.get("sanctions_status") == "hit":
            excluded.append({**supplier, "reason": "Restricted-party screening hit."})
            continue

        score = 40.0
        if category_l and category_l in (supplier.get("category") or "").lower():
            score += 25
            reasons.append("category incumbent")
        tier_bonus = {"platinum": 20, "gold": 14, "silver": 8, "bronze": 3}
        score += tier_bonus.get((supplier.get("tier") or "silver").lower(), 5)
        reasons.append(f"{supplier.get('tier')} tier")

        spend = float(supplier.get("spend_ytd_usd") or 0.0)
        if spend > 250_000:
            score += 8
            reasons.append("proven at volume")
        risk = float(supplier.get("risk_score") or 0.0)
        score -= min(20.0, risk * 0.35)
        if risk >= 35:
            reasons.append(f"elevated risk {risk:.0f}")
        if supplier.get("sanctions_status") == "review":
            score -= 10
            reasons.append("screening under adjudication")

        scored.append({**supplier, "fit_score": round(max(0.0, min(100.0, score)), 1),
                       "rationale": ", ".join(reasons)})

    scored.sort(key=lambda s: s["fit_score"], reverse=True)
    return {
        "shortlist": scored[:limit],
        "excluded": excluded,
        "considered": len(candidates),
        "requires_human_review": len(scored) < 3,
    }


# --------------------------------------------------------------------------
# Bid evaluation
# --------------------------------------------------------------------------
def score_bids(bids: list[dict], *, budget: float, weights: dict | None = None,
               incumbent_spend: float = 0.0) -> dict:
    """Score and rank bids. Every component is shown so the award is defensible."""
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    if not bids:
        return {"scored": [], "winner": None, "requires_human_review": True,
                "reason": "No bids received."}

    amounts = [float(b.get("bid_amount_usd") or 0.0) for b in bids if b.get("bid_amount_usd")]
    best, worst = (min(amounts), max(amounts)) if amounts else (0.0, 0.0)
    spread = (worst - best) or 1.0

    scored = []
    for bid in bids:
        amount = float(bid.get("bid_amount_usd") or 0.0)
        # Commercial: cheapest = 100, dearest = 60, linear between.
        commercial = 100.0 - 40.0 * ((amount - best) / spread) if amount else 0.0
        technical = float(bid.get("technical_score") or 0.0)
        risk_raw = float(bid.get("risk_score") or 0.0)      # 0-100, higher = riskier
        risk_component = 100.0 - risk_raw

        total = round(
            commercial * weights["commercial"]
            + technical * weights["technical"]
            + risk_component * weights["risk"], 2,
        )
        flags = list(bid.get("compliance_flags") or [])
        if budget and amount > budget:
            flags.append(f"over budget by {amount - budget:,.0f} USD")
        if float(bid.get("lead_time_days") or 0) > 90:
            flags.append("lead time over 90 days")

        scored.append({
            **bid,
            "commercial_score": round(commercial, 2),
            "technical_score": round(technical, 2),
            "risk_component": round(risk_component, 2),
            "total_score": total,
            "compliance_flags": flags,
            "over_budget": bool(budget and amount > budget),
        })

    scored.sort(key=lambda b: b["total_score"], reverse=True)
    winner = scored[0]
    runner_up = scored[1] if len(scored) > 1 else None
    margin = round(winner["total_score"] - runner_up["total_score"], 2) if runner_up else None

    baseline = incumbent_spend or worst
    savings = round(max(0.0, baseline - float(winner.get("bid_amount_usd") or 0.0)), 2)

    # A narrow margin, or a winner who is over budget or non-compliant, is a
    # judgement call — say so rather than presenting a false certainty.
    close_call = margin is not None and margin < 4.0
    confidence = 0.95 if not close_call and not winner["compliance_flags"] else 0.78

    return {
        "scored": scored,
        "winner": winner,
        "runner_up": runner_up,
        "margin": margin,
        "weights": weights,
        "expected_savings_usd": savings,
        "savings_pct": round(savings / baseline * 100, 2) if baseline else 0.0,
        "close_call": close_call,
        "confidence": confidence,
        "requires_human_review": True,   # awards always do
    }


def rfp_document(*, event_title: str, category: str, budget: float, requirements: list[str],
                 compliance_rules: list[str], response_due: date | None = None,
                 weights: dict | None = None, event_number: str = "") -> str:
    """Render the issuable RFP package."""
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    due = response_due or (date.today() + timedelta(days=14))
    req_lines = "\n".join(f"{i}. {r}" for i, r in enumerate(requirements, start=1)) or \
                "1. See attached requirements brief."
    rules = "\n".join(f"- {r}" for r in compliance_rules) or "- Standard supplier code of conduct."

    return f"""# Request for Proposal — {event_title}

**Event number:** {event_number or 'TBC'}
**Category:** {category}
**Indicative budget:** {budget:,.2f} USD
**Response due:** {due.isoformat()}

## 1. Scope of requirement

{req_lines}

## 2. Mandatory compliance

{rules}

## 3. Response format

Suppliers must submit:

- Commercial proposal, itemised, in USD, fixed for the contract term
- Technical response addressing each numbered requirement above
- Lead time and capacity commitment
- Evidence of insurance, tax registration and any category certifications

## 4. Evaluation

Bids are scored on published weights and the result is reproducible from them:

| Dimension | Weight |
|---|---|
| Commercial | {weights['commercial']:.0%} |
| Technical | {weights['technical']:.0%} |
| Risk & compliance | {weights['risk']:.0%} |

## 5. Process

Questions close five business days before the response deadline. Award is
subject to internal approval; this document is not an offer or a commitment to
contract.

---
*Prepared by the Sourcing Event Agent. Issued only on human approval.*
"""
