"""Vendor risk skill — continuous supplier compliance and fraud monitoring."""
from __future__ import annotations

from datetime import date, timedelta

from ..enums import RiskLevel
from ..models import Supplier, utcnow

SKILL = {
    "name": "vendor_risk",
    "title": "Vendor Risk Monitoring",
    "purpose": "Monitor sanctions, insurance, tax forms and vendor-master changes for fraud and compliance risk.",
    "inputs": ["supplier record", "recent master-data changes", "payment history"],
    "output": ["risk_score", "risk_level", "findings", "recommended_action"],
    "success_criteria": "No payment released to a sanctioned or freshly-rebanked supplier without review.",
    "failure_handling": "Any sanctions hit or bank change inside the freeze window blocks payment.",
    "used_by": ["supplier_risk", "payment_readiness"],
}

WEIGHTS = {
    "sanctions_hit": 55,
    "sanctions_review": 25,
    "bank_change_recent": 30,
    "tax_form_missing": 18,
    "tax_form_expiring": 8,
    "insurance_expired": 20,
    "insurance_expiring": 8,
    "poor_payment_history": 10,
    "new_supplier": 8,
}


def assess(supplier: Supplier, *, bank_freeze_days: int = 10, today: date | None = None) -> dict:
    today = today or date.today()
    findings: list[dict] = []
    score = 0.0

    if supplier.sanctions_status == "hit":
        score += WEIGHTS["sanctions_hit"]
        findings.append({
            "code": "sanctions_hit", "severity": RiskLevel.CRITICAL,
            "detail": "Supplier appears on a restricted-party screening list.",
            "action": "Block supplier and freeze all payments pending compliance review.",
        })
    elif supplier.sanctions_status == "review":
        score += WEIGHTS["sanctions_review"]
        findings.append({
            "code": "sanctions_review", "severity": RiskLevel.HIGH,
            "detail": "Screening returned a possible name match requiring adjudication.",
            "action": "Hold payments until compliance clears the match.",
        })

    if supplier.bank_changed_at:
        days_since = (utcnow() - supplier.bank_changed_at).days
        if days_since <= bank_freeze_days:
            score += WEIGHTS["bank_change_recent"]
            findings.append({
                "code": "bank_change_recent", "severity": RiskLevel.HIGH,
                "detail": f"Bank details changed {days_since} day(s) ago "
                          f"(freeze window is {bank_freeze_days} days).",
                "action": "Verify the change out-of-band with a known supplier contact before paying.",
            })

    if supplier.tax_form_status == "missing":
        score += WEIGHTS["tax_form_missing"]
        findings.append({
            "code": "tax_form_missing", "severity": RiskLevel.MEDIUM,
            "detail": "No valid W-9 / W-8BEN on file.",
            "action": "Request the tax form; withholding may apply.",
        })
    elif supplier.tax_form_expiry:
        days = (supplier.tax_form_expiry - today).days
        if days < 0:
            score += WEIGHTS["tax_form_missing"]
            findings.append({"code": "tax_form_expired", "severity": RiskLevel.MEDIUM,
                             "detail": f"Tax form expired {abs(days)} days ago.",
                             "action": "Request a refreshed tax certificate."})
        elif days <= 45:
            score += WEIGHTS["tax_form_expiring"]
            findings.append({"code": "tax_form_expiring", "severity": RiskLevel.LOW,
                             "detail": f"Tax form expires in {days} days.",
                             "action": "Request renewal ahead of expiry."})

    if supplier.insurance_expiry:
        days = (supplier.insurance_expiry - today).days
        if days < 0:
            score += WEIGHTS["insurance_expired"]
            findings.append({"code": "insurance_expired", "severity": RiskLevel.HIGH,
                             "detail": f"Certificate of insurance lapsed {abs(days)} days ago.",
                             "action": "Suspend new POs until cover is reinstated."})
        elif days <= 30:
            score += WEIGHTS["insurance_expiring"]
            findings.append({"code": "insurance_expiring", "severity": RiskLevel.LOW,
                             "detail": f"Insurance expires in {days} days.",
                             "action": "Chase the renewed certificate."})

    if (supplier.on_time_payment_pct or 100) < 80:
        score += WEIGHTS["poor_payment_history"]
        findings.append({"code": "poor_payment_history", "severity": RiskLevel.LOW,
                         "detail": f"On-time payment rate to this supplier is "
                                   f"{supplier.on_time_payment_pct:.0f}%.",
                         "action": "Review terms — relationship risk, not fraud risk."})

    if (supplier.invoice_count_ytd or 0) < 3:
        score += WEIGHTS["new_supplier"]
        findings.append({"code": "new_supplier", "severity": RiskLevel.LOW,
                         "detail": "Fewer than three invoices processed to date.",
                         "action": "Apply first-payment verification."})

    score = round(min(100.0, score), 1)
    if score >= 55:
        level = RiskLevel.CRITICAL
    elif score >= 35:
        level = RiskLevel.HIGH
    elif score >= 15:
        level = RiskLevel.MEDIUM
    else:
        level = RiskLevel.LOW

    blocking = [f for f in findings if f["severity"] in {RiskLevel.CRITICAL, RiskLevel.HIGH}]
    return {
        "supplier_id": supplier.id,
        "supplier_name": supplier.name,
        "risk_score": score,
        "risk_level": str(level),
        "findings": findings,
        "payment_blocking": bool(blocking),
        "recommended_action": (
            blocking[0]["action"] if blocking else "No action required — continue routine monitoring."
        ),
        "requires_human_review": bool(blocking),
    }
