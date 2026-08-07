"""Contract lifecycle skills — authoring, clause analysis, obligations, renewals."""
from __future__ import annotations

import re
from datetime import date, timedelta

SKILL = {
    "name": "contract_authoring",
    "title": "Contract Authoring",
    "purpose": "Generate MSA, SOW, NDA and amendment drafts from the standard clause library.",
    "inputs": ["contract request", "supplier", "value", "term", "category"],
    "output": ["contract_draft", "clause_manifest", "obligation_register"],
    "success_criteria": "Every generated draft contains the full mandatory clause set.",
    "failure_handling": "A draft is never issued for signature without a human approval.",
    "used_by": ["contract_lifecycle"],
}

CLAUSE_ANALYSIS = {
    "name": "clause_analysis",
    "title": "Clause Analysis",
    "purpose": "Detect missing, risky, non-standard and vendor-favouring language in a contract.",
    "inputs": ["contract document (text)", "clause library", "risk policy"],
    "output": ["missing_clauses", "risky_clauses", "legal_risk_score", "redline_notes"],
    "success_criteria": "No mandatory clause omission goes undetected.",
    "failure_handling": "Findings are advisory; Legal and Procurement decide the redline.",
    "used_by": ["contract_lifecycle"],
}

OBLIGATIONS = {
    "name": "obligation_tracking",
    "title": "Obligation & Renewal Tracking",
    "purpose": "Extract deliverables, SLAs, rebates and dates, and forecast renewal actions.",
    "inputs": ["executed contract", "term dates"],
    "output": ["obligation_register", "renewal_date", "notice_deadline"],
    "success_criteria": "No auto-renewal passes its notice window unflagged.",
    "failure_handling": "Ambiguous dates are surfaced for confirmation rather than assumed.",
    "used_by": ["contract_lifecycle"],
}

# Mandatory clause set. Each entry: key, human label, detection pattern.
MANDATORY_CLAUSES: list[tuple[str, str, str]] = [
    ("liability", "Limitation of liability", r"limitation of liability|liability cap|limit of liability"),
    ("indemnity", "Indemnification", r"indemnif"),
    ("termination", "Termination for convenience", r"terminat"),
    ("confidentiality", "Confidentiality", r"confidential"),
    ("data_protection", "Data protection", r"data protection|gdpr|personal data|privacy"),
    ("insurance", "Insurance requirements", r"insur"),
    ("audit", "Audit rights", r"audit right|right to audit|books and records"),
    ("compliance", "Anti-bribery & compliance", r"anti-?bribery|fcpa|anti-?corruption|code of conduct"),
    ("ip", "Intellectual property", r"intellectual property|\bip\b|work product"),
    ("price_protection", "Price protection", r"price protection|price increase|rate card|fixed pric"),
    ("sla", "Service levels", r"service level|\bsla\b|uptime|on-time"),
    ("assignment", "Assignment", r"assign"),
]

# Language that shifts risk to the buyer.
RISKY_PATTERNS: list[tuple[str, str, str, int]] = [
    ("unlimited_liability", "Unlimited liability exposure",
     r"unlimited liability|without limitation as to (?:amount|liability)|no cap on liability", 25),
    ("auto_renew_silent", "Automatic renewal without a notice window",
     r"automatically renew(?!.{0,120}(?:notice|written notice))", 18),
    ("unilateral_price", "Supplier may change prices unilaterally",
     r"(?:supplier|vendor|contractor) may (?:adjust|increase|change) (?:the )?(?:price|rate|fee)", 20),
    ("no_termination_convenience", "No termination for convenience",
     r"may not (?:be )?terminat|no right to terminate", 16),
    ("exclusive_venue", "Exclusive foreign jurisdiction",
     r"exclusive jurisdiction of the courts of (?!.*(?:delaware|new york|england))", 10),
    ("evergreen", "Evergreen term with no end date",
     r"perpetual term|shall continue indefinitely", 14),
    ("buyer_indemnifies", "Buyer indemnifies the supplier",
     r"(?:buyer|customer|client) shall indemnify", 22),
]


def analyze_clauses(text: str) -> dict:
    """Read a contract body and report what is missing and what is dangerous."""
    body = (text or "").lower()
    if not body.strip():
        return {"missing_clauses": [], "risky_clauses": [], "legal_risk_score": 0.0,
                "present_clauses": [], "requires_human_review": True,
                "note": "Empty document — nothing to analyse."}

    present, missing = [], []
    for key, label, pattern in MANDATORY_CLAUSES:
        if re.search(pattern, body, re.IGNORECASE):
            present.append({"key": key, "label": label})
        else:
            missing.append({"key": key, "label": label,
                            "impact": "Mandatory under the standard clause library."})

    risky = []
    score = 0.0
    for key, label, pattern, weight in RISKY_PATTERNS:
        match = re.search(pattern, body, re.IGNORECASE | re.DOTALL)
        if match:
            excerpt = " ".join(text[max(0, match.start() - 60):match.end() + 90].split())
            risky.append({"key": key, "label": label, "weight": weight, "excerpt": excerpt})
            score += weight

    # Missing mandatory clauses carry weight too — an omission is a risk.
    score += len(missing) * 6
    score = round(min(100.0, score), 1)

    redlines = [f"Add: {m['label']}" for m in missing]
    redlines += [f"Renegotiate: {r['label']}" for r in risky]

    return {
        "present_clauses": present,
        "missing_clauses": missing,
        "risky_clauses": risky,
        "legal_risk_score": score,
        "risk_band": "critical" if score >= 60 else "high" if score >= 35
        else "medium" if score >= 15 else "low",
        "redline_notes": redlines,
        "requires_human_review": bool(missing or risky),
    }


def extract_obligations(text: str, *, start: date | None = None, term_months: int = 12) -> dict:
    """Pull trackable commitments and the renewal clock out of a contract."""
    start = start or date.today()
    obligations: list[dict] = []
    body = text or ""

    for match in re.finditer(r"(\d{2,3}(?:\.\d+)?)\s*%\s*(uptime|availability|on-time|otif|sla)",
                             body, re.IGNORECASE):
        obligations.append({"type": "service_level", "metric": match.group(2).lower(),
                            "target": float(match.group(1)),
                            "detail": f"{match.group(1)}% {match.group(2)} commitment."})

    for match in re.finditer(r"(?:rebate|discount)\D{0,30}(\d+(?:\.\d+)?)\s*%", body, re.IGNORECASE):
        obligations.append({"type": "rebate", "target": float(match.group(1)),
                            "detail": f"{match.group(1)}% rebate — must be claimed."})

    for match in re.finditer(r"(?:deliver|provide|supply)\s+([^.\n]{10,90})", body, re.IGNORECASE):
        obligations.append({"type": "deliverable",
                            "detail": " ".join(match.group(1).split())[:110]})

    notice_days = 90
    notice_match = re.search(r"(\d{1,3})\s*days[^.]{0,40}(?:notice|prior written notice)",
                             body, re.IGNORECASE)
    if notice_match:
        notice_days = int(notice_match.group(1))

    renewal = start + timedelta(days=int(term_months * 30.44))
    notice_deadline = renewal - timedelta(days=notice_days)
    auto_renew = bool(re.search(r"automatically renew|auto-?renew", body, re.IGNORECASE))

    return {
        "obligations": obligations[:20],
        "obligation_count": len(obligations),
        "renewal_date": renewal.isoformat(),
        "notice_days": notice_days,
        "notice_deadline": notice_deadline.isoformat(),
        "auto_renew": auto_renew,
        "days_to_notice": (notice_deadline - date.today()).days,
        "requires_human_review": auto_renew and (notice_deadline - date.today()).days < 60,
    }


def author(*, contract_type: str, supplier_name: str, title: str, value_usd: float,
           term_months: int, category: str = "", rate_card: dict | None = None,
           reference: str = "", start: date | None = None) -> str:
    """Generate a draft from the standard clause library."""
    start = start or date.today()
    end = start + timedelta(days=int(term_months * 30.44))
    rates = rate_card or {}
    rate_rows = "\n".join(f"| {k} | {v:,.2f} USD |" for k, v in rates.items()) or \
                "| _To be scheduled_ | — |"

    return f"""# {contract_type} — {title}

**Reference:** {reference or 'DRAFT'}
**Supplier:** {supplier_name}
**Category:** {category or 'General'}
**Contract value:** {value_usd:,.2f} USD
**Term:** {start.isoformat()} to {end.isoformat()} ({term_months} months)

---

## 1. Scope
The Supplier shall provide the goods and services described in the applicable
Statement of Work, in accordance with the terms below.

## 2. Pricing and price protection
Rates are fixed for the initial term. The Supplier may not adjust prices
unilaterally. Any increase requires the Buyer's prior written agreement.

| Item | Agreed rate |
|---|---|
{rate_rows}

## 3. Service levels
The Supplier shall achieve 98% on-time-in-full delivery measured monthly.
Failure in two consecutive months entitles the Buyer to service credits.

## 4. Limitation of liability
Each party's aggregate liability is limited to the greater of the fees paid in
the preceding twelve months or {value_usd:,.0f} USD. Nothing limits liability for
death, personal injury, fraud or wilful misconduct.

## 5. Indemnification
The Supplier shall indemnify the Buyer against third-party claims arising from
the Supplier's negligence, breach of this agreement, or infringement of
intellectual property.

## 6. Confidentiality
Each party shall keep the other's confidential information secret for the term
and five years thereafter.

## 7. Data protection
Where personal data is processed, the Supplier acts as processor and shall
comply with applicable data protection law, including GDPR where in scope.

## 8. Insurance
The Supplier shall maintain commercial general liability cover of not less than
5,000,000 USD and provide certificates annually.

## 9. Audit rights
The Buyer may audit the Supplier's books and records relating to this agreement
on 15 business days' notice, not more than once per year.

## 10. Anti-bribery and compliance
The Supplier shall comply with all applicable anti-bribery and anti-corruption
law, including the FCPA and the UK Bribery Act, and with the Buyer's supplier
code of conduct.

## 11. Intellectual property
All work product created specifically for the Buyer vests in the Buyer on
creation. Pre-existing IP remains with its owner.

## 12. Term, renewal and termination
This agreement runs for {term_months} months. It does **not** renew
automatically. Either party may terminate for convenience on 90 days' written
notice, or immediately for material breach not remedied within 30 days.

## 13. Assignment
Neither party may assign without the other's prior written consent, not to be
unreasonably withheld.

## 14. Governing law
This agreement is governed by the laws of the State of Delaware, and the parties
submit to the exclusive jurisdiction of its courts.

---
*Draft generated by the Contract Lifecycle Agent from the standard clause
library. Not binding. Requires human review and approval before issue.*
"""
