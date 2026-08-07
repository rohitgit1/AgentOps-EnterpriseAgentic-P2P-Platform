"""Shared skills framework.

Each module here is one or more reusable capabilities, declared with a
descriptor that mirrors its `SKILL.md` and exposes a callable implementation.
Agents compose skills; skills never touch the system of record.

Modules with a single capability expose `SKILL`. Modules covering a related
family (sourcing, spend, contracts, tail spend) expose `SKILL` plus additional
named descriptors, all listed in `DESCRIPTORS` below.
"""
from __future__ import annotations

from . import (
    approval_routing,
    contract_lifecycle,
    contract_parsing,
    duplicate_detection,
    exception_resolution,
    invoice_extraction,
    payment_prioritization,
    po_lookup,
    sla_prediction,
    sourcing,
    spend_analysis,
    strategic_risk,
    supplier_lookup,
    tail_spend,
    tax_validation,
    variance_analysis,
    vendor_risk,
)

# --- P2P AgentOps ----------------------------------------------------------
P2P_MODULES = [
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

# --- Procurement AgentOps --------------------------------------------------
# (descriptor, implementing module) — a module may declare several skills.
PROCUREMENT_DESCRIPTORS = [
    (sourcing.SKILL, sourcing),
    (sourcing.DISCOVERY, sourcing),
    (sourcing.BID_EVALUATION, sourcing),
    (spend_analysis.SKILL, spend_analysis),
    (spend_analysis.NORMALIZATION, spend_analysis),
    (spend_analysis.SAVINGS, spend_analysis),
    (spend_analysis.MAVERICK, spend_analysis),
    (strategic_risk.SKILL, strategic_risk),
    (strategic_risk.ESG, strategic_risk),
    (contract_lifecycle.SKILL, contract_lifecycle),
    (contract_lifecycle.CLAUSE_ANALYSIS, contract_lifecycle),
    (contract_lifecycle.OBLIGATIONS, contract_lifecycle),
    (tail_spend.SKILL, tail_spend),
    (tail_spend.CATALOG, tail_spend),
    (tail_spend.CONSOLIDATION, tail_spend),
    (tail_spend.SPOT_BUY, tail_spend),
]

DESCRIPTORS: list[tuple[dict, object, str]] = (
    [(m.SKILL, m, "p2p") for m in P2P_MODULES]
    + [(d, m, "procurement") for d, m in PROCUREMENT_DESCRIPTORS]
)

MODULES = P2P_MODULES + [sourcing, spend_analysis, strategic_risk, contract_lifecycle, tail_spend]
REGISTRY = {descriptor["name"]: module for descriptor, module, _ in DESCRIPTORS}


def catalog(suite: str | None = None) -> list[dict]:
    """All declared skills, optionally filtered to one suite."""
    return [
        {**descriptor, "suite": owning_suite}
        for descriptor, _, owning_suite in DESCRIPTORS
        if suite is None or owning_suite == suite
    ]
