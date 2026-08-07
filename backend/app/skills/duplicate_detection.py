"""Duplicate detection skill — catch the same spend billed twice."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Invoice
from ..services.erp import text_similarity

SKILL = {
    "name": "duplicate_detection",
    "title": "Duplicate Detection",
    "purpose": "Detect exact and near-duplicate invoices before they reach payment.",
    "inputs": ["invoice_number", "supplier_id", "total_amount", "invoice_date", "po_number"],
    "output": ["is_duplicate", "score", "matched_invoice", "signals"],
    "success_criteria": "Zero duplicate payments; false-positive rate below 2%.",
    "failure_handling": "Any score above the policy threshold blocks the invoice for human confirmation.",
    "used_by": ["invoice_intake", "exception_resolution"],
}


def _same_supplier(a: Invoice, b: Invoice) -> bool:
    if a.supplier_id and b.supplier_id:
        return a.supplier_id == b.supplier_id
    if a.supplier_id and not b.supplier_id:
        return text_similarity(a.supplier_name_raw or "", b.supplier_name_raw or "") >= 0.72
    if b.supplier_id and not a.supplier_id:
        return text_similarity(a.supplier_name_raw or "", b.supplier_name_raw or "") >= 0.72
    return text_similarity(a.supplier_name_raw or "", b.supplier_name_raw or "") >= 0.72


def detect(db: Session, invoice: Invoice, *, threshold: float = 0.92, window_days: int = 180) -> dict:
    """Weighted-signal duplicate check across number, amount, date and PO."""
    # Match on the resolved supplier *or* the raw name on the document: a
    # duplicate frequently arrives before its twin has been resolved to vendor
    # master, and filtering on supplier_id alone would miss exactly that case.
    candidates = [
        other
        for other in db.execute(select(Invoice).where(Invoice.id != invoice.id)).scalars().all()
        if _same_supplier(invoice, other)
    ]

    best_score = 0.0
    best: Invoice | None = None
    best_signals: list[str] = []

    for other in candidates:
        if other.status in {"rejected", "cancelled"}:
            continue
        # Only compare against invoices that arrived first. The newcomer is the
        # one held; the incumbent already in flight is not disturbed.
        if other.received_at and invoice.received_at and other.received_at > invoice.received_at:
            continue
        signals: list[str] = []
        score = 0.0

        # Invoice number (strongest signal)
        num_sim = text_similarity(invoice.invoice_number or "", other.invoice_number or "")
        if num_sim >= 0.99:
            score += 0.55
            signals.append("identical invoice number")
        elif num_sim >= 0.80:
            score += 0.30
            signals.append(f"similar invoice number ({num_sim:.0%})")

        # Amount
        a, b = invoice.total_amount or 0.0, other.total_amount or 0.0
        if a and b:
            delta = abs(a - b) / max(a, b)
            if delta < 0.001:
                score += 0.28
                signals.append("identical amount")
            elif delta < 0.02:
                score += 0.14
                signals.append(f"amount within {delta:.1%}")

        # Date proximity
        if invoice.invoice_date and other.invoice_date:
            gap = abs((invoice.invoice_date - other.invoice_date).days)
            if gap == 0:
                score += 0.10
                signals.append("same invoice date")
            elif gap <= window_days:
                score += max(0.0, 0.08 * (1 - gap / window_days))
                signals.append(f"invoice dates {gap} days apart")
            else:
                continue

        # Same PO
        if invoice.po_id and other.po_id and invoice.po_id == other.po_id:
            score += 0.10
            signals.append("same purchase order")

        # Domain rule that outranks the weighted signals: the same supplier
        # billing the same invoice number for the same amount is a duplicate,
        # whatever the dates say.
        if "identical invoice number" in signals and "identical amount" in signals:
            score = max(score, 0.97)

        score = round(min(score, 1.0), 4)
        if score > best_score:
            best_score, best, best_signals = score, other, signals

    is_duplicate = best_score >= threshold
    return {
        "is_duplicate": is_duplicate,
        "score": best_score,
        "threshold": threshold,
        "signals": best_signals,
        "matched_invoice": (
            {
                "id": best.id,
                "invoice_number": best.invoice_number,
                "total_amount": best.total_amount,
                "invoice_date": best.invoice_date.isoformat() if best and best.invoice_date else None,
                "status": best.status,
                "paid_at": best.paid_at.isoformat() if best and best.paid_at else None,
            }
            if best and best_score >= 0.55
            else None
        ),
        "requires_human_review": is_duplicate or best_score >= 0.75,
    }
