"""Exception resolution skill — a playbook per exception type.

Returns a *proposal*: the recommended resolution, the confidence in it, and the
alternatives a human should weigh. It never resolves anything itself.
"""
from __future__ import annotations

from ..enums import ActionKind, ExceptionType, RiskLevel

SKILL = {
    "name": "exception_resolution",
    "title": "Exception Resolution",
    "purpose": "Diagnose an AP exception and propose the resolution a human should confirm.",
    "inputs": ["exception_type", "variance detail", "contract terms", "supplier history"],
    "output": ["recommended_action", "confidence", "alternatives", "supplier_message_draft"],
    "success_criteria": "60% of exceptions resolved on the agent's first proposal.",
    "failure_handling": "Low-confidence diagnoses escalate with the evidence attached, never a guess.",
    "used_by": ["exception_resolution", "three_way_match"],
}


def playbook(
    *,
    exception_type: str,
    context: dict,
) -> dict:
    """Return {summary, action_kind, payload_hint, confidence, alternatives, draft}."""
    exception_type = str(exception_type)
    variance = float(context.get("variance_amount") or 0.0)
    tolerance_abs = float(context.get("tolerance_abs") or 50.0)
    contract_price = context.get("contract_unit_price")
    invoice_price = context.get("invoice_unit_price")
    supplier_name = context.get("supplier_name", "the supplier")
    invoice_number = context.get("invoice_number", "the invoice")

    if exception_type == ExceptionType.PRICE_MISMATCH:
        if contract_price is not None and invoice_price is not None and invoice_price > contract_price:
            return {
                "summary": (
                    f"Invoice unit price {invoice_price:,.2f} exceeds the contracted "
                    f"{contract_price:,.2f}. Contract price governs."
                ),
                "action_kind": ActionKind.RESOLVE_EXCEPTION,
                "recommended": "short_pay_to_contract",
                "confidence": 0.93,
                "alternatives": [
                    {"option": "short_pay_to_contract",
                     "detail": "Pay at the contracted rate and notify the supplier of the adjustment.",
                     "impact_usd": -abs(variance)},
                    {"option": "request_credit_note",
                     "detail": "Pay in full now and pursue a credit note for the difference.",
                     "impact_usd": 0.0},
                    {"option": "accept_variance",
                     "detail": "Accept the higher price — requires a documented commercial reason.",
                     "impact_usd": abs(variance)},
                ],
                "draft": (
                    f"Hello,\n\nWe are processing {invoice_number}. The unit price billed "
                    f"({invoice_price:,.2f}) is above the rate on our current agreement "
                    f"({contract_price:,.2f}). We intend to pay at the contracted rate, a difference of "
                    f"{abs(variance):,.2f}. Please confirm or send a corrected invoice.\n\n"
                    f"Thank you,\nAccounts Payable"
                ),
            }
        if abs(variance) <= tolerance_abs:
            return {
                "summary": f"Price variance of {variance:,.2f} is immaterial against the "
                           f"{tolerance_abs:,.2f} absolute floor.",
                "action_kind": ActionKind.RESOLVE_EXCEPTION,
                "recommended": "accept_within_tolerance",
                "confidence": 0.95,
                "alternatives": [
                    {"option": "accept_within_tolerance",
                     "detail": "Clear the exception and continue to approval.", "impact_usd": variance},
                    {"option": "query_supplier",
                     "detail": "Ask the supplier to explain before clearing.", "impact_usd": 0.0},
                ],
                "draft": None,
            }
        return {
            "summary": f"Price variance of {variance:,.2f} has no contract reference to adjudicate against.",
            "action_kind": ActionKind.SEND_SUPPLIER_MESSAGE,
            "recommended": "query_supplier",
            "confidence": 0.74,
            "alternatives": [
                {"option": "query_supplier", "detail": "Ask the supplier for a breakdown.", "impact_usd": 0.0},
                {"option": "route_to_buyer", "detail": "Ask the buyer whether the price change was agreed.",
                 "impact_usd": 0.0},
            ],
            "draft": (
                f"Hello,\n\nWe are reviewing {invoice_number} and see a price difference of "
                f"{abs(variance):,.2f} versus the purchase order. Could you send a breakdown or a "
                f"corrected invoice?\n\nThank you,\nAccounts Payable"
            ),
        }

    if exception_type == ExceptionType.MISSING_RECEIPT:
        return {
            "summary": "No goods receipt has been posted against the PO line, so the three-way match cannot complete.",
            "action_kind": ActionKind.REQUEST_GOODS_RECEIPT,
            "recommended": "chase_receiver",
            "confidence": 0.91,
            "alternatives": [
                {"option": "chase_receiver", "detail": "Ask the requester to confirm and post receipt.",
                 "impact_usd": 0.0},
                {"option": "two_way_match_waiver",
                 "detail": "Waive receipt for a services PO under the waiver threshold.", "impact_usd": 0.0},
                {"option": "hold_until_receipt", "detail": "Hold the invoice until receipt posts.",
                 "impact_usd": 0.0},
            ],
            "draft": None,
        }

    if exception_type == ExceptionType.DUPLICATE_INVOICE:
        return {
            "summary": "This invoice closely matches one already in the system — paying both would double-pay.",
            "action_kind": ActionKind.HOLD_INVOICE,
            "recommended": "hold_and_confirm",
            "confidence": 0.96,
            "alternatives": [
                {"option": "hold_and_confirm", "detail": "Hold and confirm against the original before rejecting.",
                 "impact_usd": -abs(float(context.get("amount") or 0.0))},
                {"option": "reject_as_duplicate", "detail": "Reject outright and notify the supplier.",
                 "impact_usd": -abs(float(context.get("amount") or 0.0))},
                {"option": "not_a_duplicate", "detail": "Recurring charge — clear and continue.", "impact_usd": 0.0},
            ],
            "draft": None,
        }

    if exception_type == ExceptionType.TAX_ERROR:
        suggested = context.get("suggested_tax_amount")
        return {
            "summary": (
                f"Tax on this invoice does not reconcile. Recalculated figure: "
                f"{suggested:,.2f}." if suggested else "Tax on this invoice does not reconcile."
            ),
            "action_kind": ActionKind.UPDATE_INVOICE_FIELDS,
            "recommended": "correct_tax",
            "confidence": 0.88,
            "alternatives": [
                {"option": "correct_tax", "detail": "Post the corrected tax figure with a note.",
                 "impact_usd": float(context.get("variance_amount") or 0.0)},
                {"option": "request_corrected_invoice", "detail": "Ask the supplier to reissue.",
                 "impact_usd": 0.0},
            ],
            "draft": None,
        }

    if exception_type == ExceptionType.MISSING_PO:
        return {
            "summary": "No purchase order could be resolved for this invoice.",
            "action_kind": ActionKind.SEND_SUPPLIER_MESSAGE,
            "recommended": "request_po_reference",
            "confidence": 0.82,
            "alternatives": [
                {"option": "request_po_reference", "detail": "Ask the supplier for the PO number.",
                 "impact_usd": 0.0},
                {"option": "non_po_workflow", "detail": "Route as a non-PO invoice for cost-centre approval.",
                 "impact_usd": 0.0},
            ],
            "draft": (
                f"Hello,\n\nWe received {invoice_number} from {supplier_name} without a purchase order "
                f"reference. Please reply with the PO number so we can process payment without delay.\n\n"
                f"Thank you,\nAccounts Payable"
            ),
        }

    if exception_type == ExceptionType.CONTRACT_RATE_BREACH:
        return {
            "summary": f"Billed rates exceed the contracted rate card by {abs(variance):,.2f}.",
            "action_kind": ActionKind.RESOLVE_EXCEPTION,
            "recommended": "short_pay_to_contract",
            "confidence": 0.90,
            "alternatives": [
                {"option": "short_pay_to_contract", "detail": "Pay at contract rates.", "impact_usd": -abs(variance)},
                {"option": "escalate_to_procurement", "detail": "Refer to the contract owner.", "impact_usd": 0.0},
            ],
            "draft": None,
        }

    if exception_type == ExceptionType.SUPPLIER_DISPUTE:
        return {
            "summary": "The supplier disputes our position; a human needs to own the commercial conversation.",
            "action_kind": ActionKind.NO_OP,
            "recommended": "assign_to_ap_manager",
            "confidence": 0.55,
            "alternatives": [
                {"option": "assign_to_ap_manager", "detail": "Assign for manual handling.", "impact_usd": 0.0},
            ],
            "draft": None,
        }

    if exception_type in {ExceptionType.BANKING_CHANGE, ExceptionType.SANCTIONS_HIT}:
        return {
            "summary": "Payment-blocking compliance condition detected.",
            "action_kind": ActionKind.HOLD_INVOICE,
            "recommended": "freeze_payment",
            "confidence": 0.97,
            "alternatives": [
                {"option": "freeze_payment", "detail": "Freeze payment pending verification.", "impact_usd": 0.0},
            ],
            "draft": None,
        }

    return {
        "summary": "No playbook matches this exception type.",
        "action_kind": ActionKind.NO_OP,
        "recommended": "manual_review",
        "confidence": 0.4,
        "alternatives": [{"option": "manual_review", "detail": "Route to a human.", "impact_usd": 0.0}],
        "draft": None,
    }


def severity_for(exception_type: str, financial_impact: float) -> str:
    if str(exception_type) in {ExceptionType.SANCTIONS_HIT, ExceptionType.DUPLICATE_INVOICE}:
        return RiskLevel.CRITICAL
    if financial_impact >= 25_000:
        return RiskLevel.HIGH
    if financial_impact >= 2_500:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW
