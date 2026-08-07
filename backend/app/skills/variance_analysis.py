"""Variance analysis skill — the arithmetic core of the three-way match."""
from __future__ import annotations

SKILL = {
    "name": "variance_analysis",
    "title": "Variance Analysis",
    "purpose": "Compare invoice lines against PO lines and goods receipts, line by line.",
    "inputs": ["invoice_lines", "po_lines", "receipts", "tolerances"],
    "output": ["match_result", "line_results", "total_variance", "worst_variance_pct"],
    "success_criteria": "Every material price or quantity variance surfaced with its dollar impact.",
    "failure_handling": "Variances outside tolerance never auto-clear; they open an exception.",
    "used_by": ["three_way_match", "exception_resolution", "contract_intelligence"],
}


def _pct(actual: float, expected: float) -> float:
    if not expected:
        return 100.0 if actual else 0.0
    return round(((actual - expected) / expected) * 100, 3)


def analyze(
    *,
    invoice_lines: list[dict],
    po_lines: list[dict],
    received_qty_by_line: dict[str, float] | None = None,
    amount_tolerance_pct: float = 3.0,
    quantity_tolerance_pct: float = 2.0,
    amount_tolerance_abs: float = 50.0,
) -> dict:
    received_qty_by_line = received_qty_by_line or {}
    po_by_item = {str(line.get("item_code") or "").upper(): line for line in po_lines if line.get("item_code")}
    po_by_number = {int(line.get("line_number", 0)): line for line in po_lines}

    results: list[dict] = []
    total_invoice = 0.0
    total_expected = 0.0
    worst_price_pct = 0.0
    worst_qty_pct = 0.0
    has_missing_receipt = False
    unmatched_lines = 0

    for line in invoice_lines:
        item_key = str(line.get("item_code") or "").upper()
        po_line = po_by_item.get(item_key) or po_by_number.get(int(line.get("line_number", 0)))
        inv_qty = float(line.get("quantity") or 0.0)
        inv_price = float(line.get("unit_price") or 0.0)
        inv_total = float(line.get("line_total") or round(inv_qty * inv_price, 2))
        total_invoice += inv_total

        if po_line is None:
            unmatched_lines += 1
            results.append(
                {
                    "line_number": line.get("line_number"),
                    "item_code": line.get("item_code"),
                    "description": line.get("description"),
                    "status": "no_po_line",
                    "invoice_qty": inv_qty,
                    "invoice_unit_price": inv_price,
                    "invoice_total": inv_total,
                    "note": "No matching PO line — unauthorised charge or miscoded item.",
                    "variance_amount": inv_total,
                }
            )
            continue

        po_price = float(po_line.get("unit_price") or 0.0)
        po_qty = float(po_line.get("quantity") or 0.0)
        expected_total = round(inv_qty * po_price, 2)
        total_expected += expected_total

        price_pct = _pct(inv_price, po_price)
        received = float(received_qty_by_line.get(str(po_line.get("id")), po_line.get("received_qty") or 0.0))
        qty_pct = _pct(inv_qty, received) if received else (100.0 if inv_qty else 0.0)
        variance_amount = round(inv_total - expected_total, 2)

        statuses: list[str] = []
        price_ok = abs(price_pct) <= amount_tolerance_pct or abs(variance_amount) <= amount_tolerance_abs
        if not price_ok:
            statuses.append("price_variance")
            worst_price_pct = max(worst_price_pct, abs(price_pct))

        if received <= 0:
            statuses.append("missing_receipt")
            has_missing_receipt = True
        else:
            qty_over = inv_qty - received
            qty_ok = abs(qty_pct) <= quantity_tolerance_pct
            if not qty_ok and qty_over > 0:
                statuses.append("quantity_variance")
                worst_qty_pct = max(worst_qty_pct, abs(qty_pct))

        if inv_qty > po_qty * (1 + quantity_tolerance_pct / 100):
            statuses.append("over_po_quantity")

        results.append(
            {
                "line_number": line.get("line_number"),
                "item_code": line.get("item_code"),
                "description": line.get("description"),
                "status": statuses[0] if statuses else "matched",
                "all_statuses": statuses or ["matched"],
                "invoice_qty": inv_qty,
                "po_qty": po_qty,
                "received_qty": received,
                "invoice_unit_price": inv_price,
                "po_unit_price": po_price,
                "price_variance_pct": price_pct,
                "quantity_variance_pct": qty_pct,
                "invoice_total": inv_total,
                "expected_total": expected_total,
                "variance_amount": variance_amount,
            }
        )

    total_variance = round(total_invoice - total_expected, 2)
    total_variance_pct = _pct(total_invoice, total_expected) if total_expected else 0.0

    if unmatched_lines:
        match_result = "no_match"
    elif has_missing_receipt:
        match_result = "missing_receipt"
    elif worst_price_pct > amount_tolerance_pct:
        match_result = "price_variance"
    elif worst_qty_pct > quantity_tolerance_pct:
        match_result = "quantity_variance"
    elif abs(total_variance) <= amount_tolerance_abs and abs(total_variance_pct) <= amount_tolerance_pct:
        match_result = "matched" if abs(total_variance) < 0.01 else "within_tolerance"
    else:
        match_result = "price_variance"

    return {
        "match_result": match_result,
        "line_results": results,
        "total_invoice": round(total_invoice, 2),
        "total_expected": round(total_expected, 2),
        "total_variance": total_variance,
        "total_variance_pct": total_variance_pct,
        "worst_price_variance_pct": worst_price_pct,
        "worst_quantity_variance_pct": worst_qty_pct,
        "tolerances": {
            "amount_pct": amount_tolerance_pct,
            "quantity_pct": quantity_tolerance_pct,
            "amount_abs": amount_tolerance_abs,
        },
        "clean": match_result in {"matched", "within_tolerance"},
    }
