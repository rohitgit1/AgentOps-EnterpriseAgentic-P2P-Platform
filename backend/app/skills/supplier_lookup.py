"""Supplier lookup skill — resolve a free-text supplier name to vendor master."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Supplier
from ..services.erp import _normalize, _similarity

SKILL = {
    "name": "supplier_lookup",
    "title": "Supplier Lookup",
    "purpose": "Resolve an extracted supplier name to a vendor master record.",
    "inputs": ["supplier_name", "tax_id", "bank_last4", "remit_to_address"],
    "output": ["supplier_id", "match_score", "candidates", "compliance_flags"],
    "success_criteria": "Correct vendor resolved at score >= 0.85 with no false positives.",
    "failure_handling": "Below 0.85, return ranked candidates and require human selection.",
    "used_by": ["invoice_intake", "supplier_experience", "supplier_risk"],
}

AUTO_RESOLVE_THRESHOLD = 0.85


def lookup(db: Session, name: str, *, tax_id: str | None = None, top_n: int = 4) -> dict:
    target = _normalize(name or "")
    candidates: list[dict] = []

    for supplier in db.execute(select(Supplier)).scalars().all():
        score = max(
            _similarity(target, _normalize(supplier.name)),
            _similarity(target, _normalize(supplier.legal_name or "")),
        )
        if tax_id and supplier.tax_id and tax_id.replace("-", "") == supplier.tax_id.replace("-", ""):
            score = max(score, 0.99)
        if score <= 0.2:
            continue
        candidates.append(
            {
                "supplier_id": supplier.id,
                "code": supplier.code,
                "name": supplier.name,
                "score": round(score, 4),
                "tier": supplier.tier,
                "payment_terms": supplier.payment_terms,
                "on_hold": supplier.on_hold,
                "sanctions_status": supplier.sanctions_status,
                "risk_level": supplier.risk_level,
            }
        )

    candidates.sort(key=lambda c: c["score"], reverse=True)
    top = candidates[:top_n]
    best = top[0] if top else None
    resolved = best if best and best["score"] >= AUTO_RESOLVE_THRESHOLD else None

    flags: list[str] = []
    if resolved:
        if resolved["on_hold"]:
            flags.append("supplier_on_hold")
        if resolved["sanctions_status"] != "clear":
            flags.append(f"sanctions_{resolved['sanctions_status']}")
        if len(top) > 1 and top[1]["score"] >= resolved["score"] - 0.06:
            flags.append("ambiguous_match")

    return {
        "query": name,
        "resolved": resolved,
        "candidates": top,
        "match_score": best["score"] if best else 0.0,
        "compliance_flags": flags,
        "requires_human_review": resolved is None or "ambiguous_match" in flags,
    }
