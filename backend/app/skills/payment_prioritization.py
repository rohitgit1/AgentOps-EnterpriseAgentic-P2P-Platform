"""Payment prioritization skill.

Implements the specification's scoring model:

    payment_score = due_risk + supplier_tier + discount_value + sla_risk

Each component is bounded and returned separately so a Treasury reviewer can
see exactly why one invoice outranks another.
"""
from __future__ import annotations

from datetime import date

SKILL = {
    "name": "payment_prioritization",
    "title": "Payment Prioritization",
    "purpose": "Rank approved invoices for the payment run by urgency, discount value and risk.",
    "inputs": ["due_date", "supplier_tier", "discount_terms", "sla_risk", "amount"],
    "output": ["priority_score", "score_breakdown", "recommended_pay_date", "discount_opportunity"],
    "success_criteria": "Capture >95% of available early-pay discounts with zero late payments on tier-1 suppliers.",
    "failure_handling": "Never schedules payment itself — Treasury approves the run.",
    "used_by": ["payment_readiness"],
}

TIER_WEIGHT = {"platinum": 25.0, "gold": 18.0, "silver": 10.0, "bronze": 5.0}


def score(
    *,
    amount: float,
    due_date: date | None,
    supplier_tier: str = "silver",
    early_pay_discount_pct: float = 0.0,
    early_pay_discount_days: int = 0,
    invoice_date: date | None = None,
    sla_risk_score: float = 0.0,
    today: date | None = None,
) -> dict:
    today = today or date.today()

    # --- due_risk: 0-40, climbing sharply as the due date passes ----------
    if due_date is None:
        days_to_due = 30
    else:
        days_to_due = (due_date - today).days
    if days_to_due < 0:
        due_risk = 40.0
    elif days_to_due <= 3:
        due_risk = 34.0
    elif days_to_due <= 7:
        due_risk = 26.0
    elif days_to_due <= 14:
        due_risk = 16.0
    elif days_to_due <= 30:
        due_risk = 8.0
    else:
        due_risk = 3.0

    # --- supplier_tier: 0-25 ---------------------------------------------
    tier_score = TIER_WEIGHT.get((supplier_tier or "silver").lower(), 10.0)

    # --- discount_value: 0-25, only if the window is still open -----------
    discount_amount = 0.0
    discount_deadline = None
    discount_score = 0.0
    if early_pay_discount_pct > 0 and invoice_date is not None and early_pay_discount_days > 0:
        from datetime import timedelta

        discount_deadline = invoice_date + timedelta(days=early_pay_discount_days)
        if discount_deadline >= today:
            discount_amount = round(amount * (early_pay_discount_pct / 100.0), 2)
            days_left = (discount_deadline - today).days
            urgency = 1.0 if days_left <= 2 else 0.8 if days_left <= 5 else 0.6
            # Scale by absolute value too: a 2% discount on $500k outranks 2% on $500.
            magnitude = min(1.0, discount_amount / 5_000.0)
            discount_score = round(25.0 * urgency * max(0.35, magnitude), 2)

    # --- sla_risk: 0-10 ---------------------------------------------------
    sla_component = round(min(10.0, (sla_risk_score or 0.0) / 10.0), 2)

    total = round(due_risk + tier_score + discount_score + sla_component, 2)

    if discount_deadline and discount_amount > 0:
        recommended = min(discount_deadline, due_date or discount_deadline)
    elif due_date:
        recommended = due_date
    else:
        recommended = today

    return {
        "priority_score": total,
        "score_breakdown": {
            "due_risk": due_risk,
            "supplier_tier": tier_score,
            "discount_value": discount_score,
            "sla_risk": sla_component,
        },
        "days_to_due": days_to_due,
        "discount_opportunity": {
            "available": discount_amount > 0,
            "amount": discount_amount,
            "pct": early_pay_discount_pct,
            "deadline": discount_deadline.isoformat() if discount_deadline else None,
        },
        "recommended_pay_date": recommended.isoformat(),
        "overdue": days_to_due < 0,
    }
