"""Shared skills framework.

Each module here is one reusable capability, declared with a `SKILL` descriptor
that mirrors its `SKILL.md` and exposes a callable implementation. Agents
compose skills; skills never touch the system of record.
"""
from __future__ import annotations

from . import (
    approval_routing,
    contract_parsing,
    duplicate_detection,
    exception_resolution,
    invoice_extraction,
    payment_prioritization,
    po_lookup,
    sla_prediction,
    supplier_lookup,
    tax_validation,
    variance_analysis,
    vendor_risk,
)

MODULES = [
    invoice_extraction,
    supplier_lookup,
    po_lookup,
    duplicate_detection,
    tax_validation,
    variance_analysis,
    contract_parsing,
    approval_routing,
    sla_prediction,
    vendor_risk,
    payment_prioritization,
    exception_resolution,
]

REGISTRY = {module.SKILL["name"]: module for module in MODULES}


def catalog() -> list[dict]:
    return [dict(module.SKILL) for module in MODULES]
