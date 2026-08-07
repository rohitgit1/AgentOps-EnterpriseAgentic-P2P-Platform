"""PO lookup skill — locate the purchase order backing an invoice."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PurchaseOrder
from ..services.erp import get_connector

SKILL = {
    "name": "po_lookup",
    "title": "Purchase Order Lookup",
    "purpose": "Find the PO an invoice bills against, directly or by supplier + amount inference.",
    "inputs": ["po_number", "supplier_id", "invoice_total", "invoice_date"],
    "output": ["po_id", "po_number", "open_amount", "lines", "inference_basis"],
    "success_criteria": "PO resolved for >= 95% of PO-backed invoices.",
    "failure_handling": "If no PO is found, raise a missing_po exception for human triage.",
    "used_by": ["invoice_intake", "three_way_match"],
}


def lookup(
    db: Session,
    *,
    po_number: str | None,
    supplier_id: str | None = None,
    invoice_total: float | None = None,
    erp_system: str | None = None,
) -> dict:
    connector = get_connector(erp_system)
    po = connector.fetch_po(db, po_number or "")
    basis = "direct_reference" if po else None

    # Fall back to inference: same supplier, open PO, remaining value covers the invoice.
    inferred_candidates: list[dict] = []
    if po is None and supplier_id:
        rows = db.execute(
            select(PurchaseOrder).where(
                PurchaseOrder.supplier_id == supplier_id,
                PurchaseOrder.status == "open",
            )
        ).scalars().all()
        for candidate in rows:
            remaining = (candidate.total_amount or 0.0) - (candidate.invoiced_amount or 0.0)
            score = 0.5
            if invoice_total and remaining > 0:
                ratio = min(invoice_total, remaining) / max(invoice_total, remaining)
                score = round(0.4 + 0.5 * ratio, 4)
            inferred_candidates.append(
                {
                    "po_id": candidate.id,
                    "po_number": candidate.po_number,
                    "remaining": round(remaining, 2),
                    "score": score,
                    "description": candidate.description,
                }
            )
        inferred_candidates.sort(key=lambda c: c["score"], reverse=True)
        if inferred_candidates and inferred_candidates[0]["score"] >= 0.85:
            po = db.get(PurchaseOrder, inferred_candidates[0]["po_id"])
            basis = "supplier_amount_inference"

    if po is None:
        return {
            "found": False,
            "po_id": None,
            "po_number": po_number,
            "candidates": inferred_candidates[:3],
            "inference_basis": None,
            "requires_human_review": True,
        }

    open_amount = round((po.total_amount or 0.0) - (po.invoiced_amount or 0.0), 2)
    return {
        "found": True,
        "po_id": po.id,
        "po_number": po.po_number,
        "supplier_id": po.supplier_id,
        "currency": po.currency,
        "total_amount": po.total_amount,
        "invoiced_amount": po.invoiced_amount,
        "received_amount": po.received_amount,
        "open_amount": open_amount,
        "cost_center": po.cost_center,
        "gl_account": po.gl_account,
        "buyer_id": po.buyer_id,
        "requester_id": po.requester_id,
        "contract_id": po.contract_id,
        "lines": [
            {
                "id": line.id,
                "line_number": line.line_number,
                "item_code": line.item_code,
                "description": line.description,
                "uom": line.uom,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "line_total": line.line_total,
                "received_qty": line.received_qty,
                "invoiced_qty": line.invoiced_qty,
            }
            for line in sorted(po.lines, key=lambda l: l.line_number)
        ],
        "inference_basis": basis,
        "requires_human_review": basis == "supplier_amount_inference",
    }
