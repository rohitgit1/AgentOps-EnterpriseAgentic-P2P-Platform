"""Strategic supplier risk — financial, operational, compliance and ESG domains.

Distinct from `vendor_risk`, which screens a supplier at payment time. This
skill produces the periodic scorecard that decides whether the company should
keep buying from them at all.
"""
from __future__ import annotations

from datetime import date

SKILL = {
    "name": "supplier_risk_assessment",
    "title": "Strategic Supplier Risk Assessment",
    "purpose": "Score a supplier across financial, operational, compliance and ESG risk.",
    "inputs": ["supplier master", "financial indicators", "certificates", "delivery history"],
    "output": ["domain_scores", "overall_risk", "risk_band", "findings", "recommended_disposition"],
    "success_criteria": "Every score traces to named findings; no unexplained numbers.",
    "failure_handling": "Disposition is a recommendation — approve/monitor/watchlist/block is a human call.",
    "used_by": ["supplier_risk_compliance"],
}

ESG = {
    "name": "esg_scoring",
    "title": "ESG Assessment",
    "purpose": "Assess sustainability, human-rights and diversity exposure for a supplier.",
    "inputs": ["esg disclosures", "country risk", "diversity certification"],
    "output": ["esg_risk", "esg_findings"],
    "success_criteria": "Disclosure gaps are reported as gaps, not scored as zero risk.",
    "failure_handling": "Absent data raises uncertainty rather than silently passing.",
    "used_by": ["supplier_risk_compliance"],
}

# Countries carrying elevated inherent ESG / human-rights exposure (demo reference).
ESG_COUNTRY_RISK = {
    "United States": 8, "Canada": 8, "United Kingdom": 9, "Germany": 8, "France": 10,
    "Netherlands": 8, "Ireland": 9, "Singapore": 14, "Australia": 9, "India": 34,
}

DISPOSITIONS = ["approve", "monitor", "watchlist", "block"]


def _band(score: float) -> str:
    if score >= 65:
        return "critical"
    if score >= 45:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def assess(
    supplier: dict,
    *,
    financials: dict | None = None,
    delivery: dict | None = None,
    today: date | None = None,
) -> dict:
    """Produce the four-domain scorecard.

    ``financials`` and ``delivery`` are optional; when absent the domain is
    scored on what is known and the gap is reported as a finding, so a missing
    feed never reads as a clean bill of health.
    """
    today = today or date.today()
    financials = financials or {}
    delivery = delivery or {}
    findings: list[dict] = []

    # ---- Financial -------------------------------------------------------
    financial = 0.0
    credit = (financials.get("credit_rating") or "").upper()
    credit_scale = {"AAA": 0, "AA": 4, "A": 8, "BBB": 18, "BB": 34, "B": 48, "CCC": 68, "D": 90}
    if credit in credit_scale:
        financial += credit_scale[credit]
        if credit_scale[credit] >= 34:
            findings.append({"domain": "financial", "severity": "high",
                             "detail": f"Credit rating {credit} is sub-investment grade."})
    else:
        financial += 22
        findings.append({"domain": "financial", "severity": "medium",
                         "detail": "No credit rating on file — financial risk is unmeasured."})

    dso = financials.get("days_beyond_terms")
    if dso is not None and float(dso) > 15:
        financial += 14
        findings.append({"domain": "financial", "severity": "medium",
                         "detail": f"Paying own suppliers {float(dso):.0f} days beyond terms — "
                                   f"a liquidity signal."})
    if financials.get("bankruptcy_flag"):
        financial += 45
        findings.append({"domain": "financial", "severity": "critical",
                         "detail": "Insolvency or bankruptcy proceeding reported."})

    # ---- Operational -----------------------------------------------------
    operational = 0.0
    otif = delivery.get("otif_pct")
    if otif is not None:
        if float(otif) < 85:
            operational += 32
            findings.append({"domain": "operational", "severity": "high",
                             "detail": f"On-time-in-full at {float(otif):.0f}% against a 95% expectation."})
        elif float(otif) < 95:
            operational += 14
            findings.append({"domain": "operational", "severity": "medium",
                             "detail": f"On-time-in-full at {float(otif):.0f}%."})
    else:
        operational += 15
        findings.append({"domain": "operational", "severity": "low",
                         "detail": "No delivery performance data captured."})

    if delivery.get("single_source"):
        operational += 22
        findings.append({"domain": "operational", "severity": "high",
                         "detail": "Single-sourced category — no qualified alternative."})
    capacity = delivery.get("capacity_utilisation_pct")
    if capacity is not None and float(capacity) > 90:
        operational += 12
        findings.append({"domain": "operational", "severity": "medium",
                         "detail": f"Supplier running at {float(capacity):.0f}% capacity; "
                                   f"little headroom for volume growth."})

    # ---- Compliance ------------------------------------------------------
    compliance = 0.0
    if supplier.get("sanctions_status") == "hit":
        compliance += 80
        findings.append({"domain": "compliance", "severity": "critical",
                         "detail": "Restricted-party screening hit."})
    elif supplier.get("sanctions_status") == "review":
        compliance += 34
        findings.append({"domain": "compliance", "severity": "high",
                         "detail": "Screening returned a possible match awaiting adjudication."})

    if supplier.get("tax_form_status") == "missing":
        compliance += 18
        findings.append({"domain": "compliance", "severity": "medium",
                         "detail": "No valid tax certification on file."})

    insurance_expiry = supplier.get("insurance_expiry")
    if isinstance(insurance_expiry, str):
        try:
            insurance_expiry = date.fromisoformat(insurance_expiry)
        except ValueError:
            insurance_expiry = None
    if insurance_expiry:
        days = (insurance_expiry - today).days
        if days < 0:
            compliance += 26
            findings.append({"domain": "compliance", "severity": "high",
                             "detail": f"Certificate of insurance lapsed {abs(days)} days ago."})
        elif days <= 30:
            compliance += 9
            findings.append({"domain": "compliance", "severity": "low",
                             "detail": f"Insurance expires in {days} days."})
    else:
        compliance += 12
        findings.append({"domain": "compliance", "severity": "medium",
                         "detail": "No certificate of insurance recorded."})

    # ---- ESG -------------------------------------------------------------
    esg = float(ESG_COUNTRY_RISK.get(supplier.get("country", ""), 25))
    if not supplier.get("esg_disclosure"):
        esg += 20
        findings.append({"domain": "esg", "severity": "medium",
                         "detail": "No ESG disclosure on file — exposure is unverified, not absent."})
    if supplier.get("diverse_supplier"):
        esg = max(0.0, esg - 6)

    domains = {
        "financial_risk": round(min(100.0, financial), 1),
        "operational_risk": round(min(100.0, operational), 1),
        "compliance_risk": round(min(100.0, compliance), 1),
        "esg_risk": round(min(100.0, esg), 1),
    }
    # Compliance is weighted hardest: it is the domain that stops trade outright.
    overall = round(
        domains["financial_risk"] * 0.30
        + domains["operational_risk"] * 0.25
        + domains["compliance_risk"] * 0.30
        + domains["esg_risk"] * 0.15, 1,
    )
    band = _band(overall)

    if domains["compliance_risk"] >= 70 or overall >= 65:
        disposition = "block"
    elif overall >= 45:
        disposition = "watchlist"
    elif overall >= 25:
        disposition = "monitor"
    else:
        disposition = "approve"

    return {
        "supplier_id": supplier.get("id"),
        "supplier_name": supplier.get("name"),
        **domains,
        "overall_risk": overall,
        "risk_band": band,
        "findings": findings,
        "recommended_disposition": disposition,
        "confidence": 0.72 if len([f for f in findings if "no " in f["detail"].lower()]) >= 2 else 0.9,
        "requires_human_review": disposition in {"watchlist", "block"},
    }
