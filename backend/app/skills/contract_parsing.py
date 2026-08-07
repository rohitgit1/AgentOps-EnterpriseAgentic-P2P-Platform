"""Contract intelligence skill — enforce the paper against what is billed."""
from __future__ import annotations

from datetime import date

SKILL = {
    "name": "contract_parsing",
    "title": "Contract Intelligence",
    "purpose": "Compare billed lines against the contracted rate card, term dates and allowed charges.",
    "inputs": ["contract", "invoice_lines", "invoice_date"],
    "output": ["findings", "recoverable_amount", "expired", "missed_discounts"],
    "success_criteria": "Every unauthorised charge and off-rate line detected before payment.",
    "failure_handling": "Findings are proposals; Procurement decides whether to short-pay or accept.",
    "used_by": ["contract_intelligence"],
}


def analyze(
    *,
    contract: dict | None,
    invoice_lines: list[dict],
    invoice_date: date | None = None,
    invoice_total: float = 0.0,
) -> dict:
    today = invoice_date or date.today()
    findings: list[dict] = []
    recoverable = 0.0

    if not contract:
        return {
            "has_contract": False,
            "findings": [],
            "recoverable_amount": 0.0,
            "expired": False,
            "missed_discounts": [],
            "requires_human_review": False,
        }

    # --- term validity ---------------------------------------------------
    end_date = contract.get("end_date")
    start_date = contract.get("start_date")
    expired = bool(end_date and today > end_date)
    if expired:
        findings.append({
            "code": "expired_pricing",
            "severity": "high",
            "detail": f"Contract {contract.get('contract_number')} expired on {end_date}; "
                      f"pricing on this invoice is no longer governed by an active agreement.",
            "impact_usd": 0.0,
        })
    if start_date and today < start_date:
        findings.append({
            "code": "pre_term_billing",
            "severity": "medium",
            "detail": f"Invoice predates the contract start date ({start_date}).",
            "impact_usd": 0.0,
        })

    # --- rate card enforcement -------------------------------------------
    rate_card = {str(k).upper(): float(v) for k, v in (contract.get("rate_card") or {}).items()}
    allowed = {str(c).lower() for c in (contract.get("allowed_charges") or [])}

    for line in invoice_lines:
        item = str(line.get("item_code") or "").upper()
        description = str(line.get("description") or "")
        qty = float(line.get("quantity") or 0.0)
        unit_price = float(line.get("unit_price") or 0.0)
        line_total = float(line.get("line_total") or qty * unit_price)

        if item and item in rate_card:
            agreed = rate_card[item]
            if unit_price > agreed + 0.005:
                overcharge = round((unit_price - agreed) * qty, 2)
                recoverable += overcharge
                findings.append({
                    "code": "incorrect_rate",
                    "severity": "high" if overcharge >= 1000 else "medium",
                    "detail": f"Line {line.get('line_number')} ({description or item}) billed at "
                              f"{unit_price:,.2f} against a contracted {agreed:,.2f} — "
                              f"overcharge {overcharge:,.2f}.",
                    "impact_usd": overcharge,
                    "line_number": line.get("line_number"),
                    "contract_unit_price": agreed,
                    "invoice_unit_price": unit_price,
                })
        elif allowed:
            haystack = f"{item} {description}".lower()
            if not any(token in haystack for token in allowed):
                recoverable += line_total
                findings.append({
                    "code": "unauthorized_charge",
                    "severity": "high",
                    "detail": f"Line {line.get('line_number')} ({description or item}, "
                              f"{line_total:,.2f}) is not an allowed charge type under this contract.",
                    "impact_usd": line_total,
                    "line_number": line.get("line_number"),
                })

    # --- volume discounts we should have received ------------------------
    missed: list[dict] = []
    for tier in contract.get("volume_discounts") or []:
        threshold = float(tier.get("threshold_usd", 0))
        pct = float(tier.get("discount_pct", 0))
        if invoice_total >= threshold > 0 and pct > 0:
            value = round(invoice_total * pct / 100.0, 2)
            missed.append({"threshold_usd": threshold, "discount_pct": pct, "value_usd": value})
            recoverable += value
            findings.append({
                "code": "missed_discount",
                "severity": "medium",
                "detail": f"Invoice total {invoice_total:,.2f} passes the {threshold:,.0f} volume tier — "
                          f"a {pct:.1f}% discount ({value:,.2f}) does not appear on the invoice.",
                "impact_usd": value,
            })

    return {
        "has_contract": True,
        "contract_number": contract.get("contract_number"),
        "findings": findings,
        "recoverable_amount": round(recoverable, 2),
        "expired": expired,
        "missed_discounts": missed,
        "requires_human_review": bool(findings),
    }
