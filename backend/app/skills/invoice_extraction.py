"""Invoice extraction skill — PDF / image / email / EDI to structured fields."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

SKILL = {
    "name": "invoice_extraction",
    "title": "Invoice Extraction",
    "purpose": "Extract structured invoice data from PDF, image, email body or EDI payload.",
    "inputs": ["PDF", "JPEG", "TIFF", "email body", "EDI 810"],
    "output": [
        "supplier_name", "invoice_number", "invoice_date", "due_date",
        "po_number", "subtotal", "tax_amount", "total_amount", "currency", "lines",
    ],
    "success_criteria": "Field-level accuracy > 98%; header confidence > 0.90.",
    "failure_handling": "If confidence < 0.90, route to human review rather than proposing an advance.",
    "used_by": ["invoice_intake"],
}

_MONEY = r"([$€£]?\s?[\d,]+\.\d{2})"

# `(?<![-\w])` keeps "Total" inside "Sub-Total" and "Line Total" from being read
# as the invoice total — the single most common extraction error on real documents.
_PATTERNS = {
    "invoice_number": r"(?:invoice|inv|bill)\s*(?:no\.?|number|nbr|#)?\s*[:#]\s*([A-Z0-9][A-Z0-9\-\/\.]{3,})",
    "po_number": r"(?:p\.?o\.?|purchase\s*order)\s*(?:no\.?|number|nbr|#)?\s*[:#]?\s*([A-Z0-9][A-Z0-9\-]{2,})",
    "total": (
        r"(?:total\s*due|amount\s*due|balance\s*due|grand\s*total|(?<![-\w])total\s*amount"
        rf"|(?<![-\w])total)\s*[:\-]?\s*{_MONEY}"
    ),
    "subtotal": rf"(?:sub\s*-?\s*total|net\s*amount)\s*[:\-]?\s*{_MONEY}",
    "tax": rf"(?<![-\w])(?:sales\s*tax|tax|vat|gst)\s*(?:\([\d.]+\s*%\))?\s*[:\-]?\s*{_MONEY}",
    "freight": rf"(?<![-\w])(?:freight|shipping|delivery)\s*[:\-]?\s*{_MONEY}",
    "invoice_date": r"(?:invoice\s*date|date\s*of\s*issue|issued)\s*[:\-]?\s*([0-9]{1,4}[\-\/][0-9]{1,2}[\-\/][0-9]{2,4}|[A-Z][a-z]{2,8}\s+\d{1,2},?\s+\d{4})",
    "due_date": r"(?:due\s*date|payment\s*due)\s*[:\-]?\s*([0-9]{1,4}[\-\/][0-9]{1,2}[\-\/][0-9]{2,4}|[A-Z][a-z]{2,8}\s+\d{1,2},?\s+\d{4})",
    "currency": r"\b(USD|EUR|GBP|CAD|INR|JPY|AUD|CHF)\b",
    "supplier": r"(?:from|supplier|vendor|remit\s*to|bill\s*from)\s*[:\-]?\s*([A-Z][\w&.,'\- ]{2,60})",
}

_CHANNEL_QUALITY = {
    "edi": 1.00,      # structured payload, nothing to misread
    "portal": 0.99,
    "pdf": 0.96,      # native text layer
    "email": 0.94,
    "scan": 0.86,     # OCR on a scanned image
}


def _money(raw: str | None) -> float | None:
    if not raw:
        return None
    cleaned = re.sub(r"[^\d.]", "", raw)
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    raw = raw.strip().replace(",", "")
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y", "%d-%m-%Y", "%B %d %Y", "%b %d %Y", "%m/%d/%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def extract(document_text: str, *, channel: str = "pdf", hints: dict | None = None) -> dict:
    """Return extracted fields plus per-field and header confidence.

    Deterministic: the same document always yields the same result, which is
    what makes the demo reproducible and the audit trail defensible.
    """
    hints = hints or {}
    text = document_text or ""
    flat = " ".join(text.split())
    fields: dict = {}
    field_confidence: dict[str, float] = {}
    base = _CHANNEL_QUALITY.get((channel or "pdf").lower(), 0.92)

    def capture(name: str, pattern_key: str, transform=lambda v: v.strip(), require_digit: bool = False):
        value = None
        for match in re.finditer(_PATTERNS[pattern_key], flat, re.IGNORECASE):
            candidate = transform(match.group(1))
            # A reference that is a bare word ("Number", "Order") is a label the
            # regex walked past, not an identifier. Real references carry digits.
            if require_digit and not any(ch.isdigit() for ch in candidate):
                continue
            value = candidate
            break
        if value:
            fields[name] = value
            field_confidence[name] = round(base, 4)
        else:
            fields[name] = hints.get(name)
            field_confidence[name] = 0.55 if hints.get(name) else 0.0

    capture("invoice_number", "invoice_number", require_digit=True)
    capture("po_number", "po_number", require_digit=True)
    capture("supplier_name", "supplier")
    invoice_date_match = re.search(_PATTERNS["invoice_date"], flat, re.IGNORECASE)
    fields["invoice_date"] = _parse_date(
        invoice_date_match.group(1) if invoice_date_match else None
    ) or hints.get("invoice_date")
    field_confidence["invoice_date"] = round(base, 4) if fields["invoice_date"] else 0.0

    due_match = re.search(_PATTERNS["due_date"], flat, re.IGNORECASE)
    fields["due_date"] = _parse_date(due_match.group(1) if due_match else None) or hints.get("due_date")
    field_confidence["due_date"] = round(base, 4) if fields["due_date"] else 0.0

    for name, key in (("total_amount", "total"), ("subtotal", "subtotal"),
                      ("tax_amount", "tax"), ("freight_amount", "freight")):
        match = re.search(_PATTERNS[key], flat, re.IGNORECASE)
        value = _money(match.group(1)) if match else hints.get(name)
        fields[name] = value
        field_confidence[name] = round(base, 4) if match else (0.6 if value is not None else 0.0)

    currency_match = re.search(_PATTERNS["currency"], flat)
    fields["currency"] = (currency_match.group(1) if currency_match else hints.get("currency")) or "USD"
    field_confidence["currency"] = 0.97 if currency_match else 0.75

    # Arithmetic self-check: a document whose parts add up is far more trustworthy.
    arithmetic_ok = None
    total = fields.get("total_amount")
    subtotal = fields.get("subtotal")
    tax = fields.get("tax_amount") or 0.0
    freight = fields.get("freight_amount") or 0.0
    if total is not None and subtotal is not None:
        arithmetic_ok = abs((subtotal + tax + freight) - total) <= 0.05 * max(1.0, total * 0.01)

    if fields.get("due_date") is None and fields.get("invoice_date"):
        terms_days = int(hints.get("terms_days", 30))
        fields["due_date"] = fields["invoice_date"] + timedelta(days=terms_days)
        field_confidence["due_date"] = 0.8

    critical = ["invoice_number", "supplier_name", "total_amount", "invoice_date"]
    critical_scores = [field_confidence.get(f, 0.0) for f in critical]
    header_confidence = round(sum(critical_scores) / len(critical_scores), 4) if critical_scores else 0.0
    if arithmetic_ok is True:
        header_confidence = round(min(0.995, header_confidence + 0.04), 4)
    elif arithmetic_ok is False:
        header_confidence = round(max(0.0, header_confidence - 0.18), 4)

    missing = [f for f in critical if not fields.get(f)]

    return {
        "fields": fields,
        "field_confidence": field_confidence,
        "confidence": header_confidence,
        "arithmetic_consistent": arithmetic_ok,
        "missing_critical_fields": missing,
        "channel": channel,
        "requires_human_review": header_confidence < 0.90 or bool(missing),
    }
