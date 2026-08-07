"""Tax validation skill — verify tax arithmetic and jurisdictional rate sanity."""
from __future__ import annotations

SKILL = {
    "name": "tax_validation",
    "title": "Tax Validation",
    "purpose": "Validate tax arithmetic, applicable rate and supplier tax registration.",
    "inputs": ["subtotal", "tax_amount", "total_amount", "supplier_country", "tax_id"],
    "output": ["valid", "effective_rate", "expected_rate_band", "findings"],
    "success_criteria": "Every material tax error detected before posting.",
    "failure_handling": "Raise a tax_error exception with the recalculated figure for human confirmation.",
    "used_by": ["invoice_intake", "exception_resolution"],
}

# Indicative standard-rate bands by jurisdiction (demo reference data).
RATE_BANDS: dict[str, tuple[float, float]] = {
    "United States": (0.0, 11.0),
    "Canada": (5.0, 15.0),
    "United Kingdom": (0.0, 20.0),
    "Germany": (7.0, 19.0),
    "France": (5.5, 20.0),
    "Netherlands": (9.0, 21.0),
    "India": (5.0, 28.0),
    "Ireland": (13.5, 23.0),
    "Singapore": (8.0, 9.0),
    "Australia": (10.0, 10.0),
}

TOLERANCE_USD = 0.05


def validate(
    *,
    subtotal: float | None,
    tax_amount: float | None,
    total_amount: float | None,
    freight_amount: float = 0.0,
    supplier_country: str = "United States",
    tax_id: str | None = None,
) -> dict:
    findings: list[str] = []
    subtotal = float(subtotal or 0.0)
    tax_amount = float(tax_amount or 0.0)
    freight_amount = float(freight_amount or 0.0)
    total_amount = float(total_amount or 0.0)

    computed_total = round(subtotal + tax_amount + freight_amount, 2)
    arithmetic_delta = round(total_amount - computed_total, 2)
    arithmetic_ok = abs(arithmetic_delta) <= TOLERANCE_USD
    if not arithmetic_ok:
        findings.append(
            f"Header does not foot: subtotal {subtotal:,.2f} + tax {tax_amount:,.2f} "
            f"+ freight {freight_amount:,.2f} = {computed_total:,.2f}, "
            f"but total reads {total_amount:,.2f} (delta {arithmetic_delta:+,.2f})."
        )

    effective_rate = round((tax_amount / subtotal) * 100, 3) if subtotal else 0.0
    low, high = RATE_BANDS.get(supplier_country, (0.0, 25.0))
    rate_ok = tax_amount == 0.0 or low - 0.5 <= effective_rate <= high + 0.5
    if not rate_ok:
        findings.append(
            f"Effective tax rate {effective_rate:.2f}% sits outside the {low:.1f}%-{high:.1f}% "
            f"band expected for {supplier_country}."
        )

    registration_ok = True
    if tax_amount > 0 and not tax_id:
        registration_ok = False
        findings.append("Tax charged but no supplier tax registration number is on file.")

    suggested_tax = round(subtotal * (high / 100), 2) if not rate_ok and subtotal else None

    valid = arithmetic_ok and rate_ok and registration_ok
    return {
        "valid": valid,
        "arithmetic_ok": arithmetic_ok,
        "arithmetic_delta": arithmetic_delta,
        "computed_total": computed_total,
        "effective_rate": effective_rate,
        "expected_rate_band": [low, high],
        "rate_ok": rate_ok,
        "registration_ok": registration_ok,
        "suggested_tax_amount": suggested_tax,
        "findings": findings,
        "requires_human_review": not valid,
    }
