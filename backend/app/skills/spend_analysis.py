"""Spend skills — classification, supplier normalization, savings and maverick detection."""
from __future__ import annotations

import re
from collections import defaultdict

from ..services.erp import text_similarity

SKILL = {
    "name": "spend_classification",
    "title": "Spend Classification",
    "purpose": "Map raw spend transactions to a category taxonomy (UNSPSC / NAICS / custom).",
    "inputs": ["spend extract (CSV)", "supplier master", "category taxonomy"],
    "output": ["category", "unspsc", "classification_confidence", "unclassified_residual"],
    "success_criteria": "≥95% of spend value classified; low-confidence rows never auto-published.",
    "failure_handling": "Rows below the confidence floor are returned as unclassified for a human.",
    "used_by": ["spend_analytics", "tail_spend"],
}

NORMALIZATION = {
    "name": "supplier_normalization",
    "title": "Supplier Normalization",
    "purpose": "Collapse supplier name variants onto a single vendor master identity.",
    "inputs": ["supplier_raw strings", "vendor master"],
    "output": ["supplier_id", "match_score", "duplicate_clusters"],
    "success_criteria": "Duplicate vendor clusters surfaced with their combined spend.",
    "failure_handling": "Ambiguous matches are listed as candidates, never merged automatically.",
    "used_by": ["spend_analytics", "tail_spend"],
}

SAVINGS = {
    "name": "savings_identification",
    "title": "Savings Identification",
    "purpose": "Quantify consolidation, contract-coverage, volume-discount and rationalization levers.",
    "inputs": ["classified spend", "contracts", "supplier master"],
    "output": ["opportunities", "estimated_savings_usd", "confidence", "rationale"],
    "success_criteria": "Every opportunity carries an addressable-spend basis and a stated rate.",
    "failure_handling": "Opportunities are proposals — none enters the savings pipeline unapproved.",
    "used_by": ["spend_analytics"],
}

MAVERICK = {
    "name": "maverick_detection",
    "title": "Maverick Spend Detection",
    "purpose": "Detect off-contract and off-catalog buying that bypasses negotiated channels.",
    "inputs": ["classified spend", "contract coverage", "preferred supplier list"],
    "output": ["maverick_transactions", "maverick_spend_usd", "contract_compliance_pct"],
    "success_criteria": "Contract compliance measured on value, not transaction count.",
    "failure_handling": "Flags are advisory until a human approves an enforcement action.",
    "used_by": ["spend_analytics", "tail_spend"],
}

# Keyword → (category, UNSPSC segment). Deliberately explicit so a classification
# can always be explained by the token that produced it.
TAXONOMY: list[tuple[str, str, str]] = [
    (r"\b(laptop|monitor|server|workstation|hardware|peripheral)\b", "IT Hardware", "43211500"),
    (r"\b(licen[cs]e|software|saas|subscription|platform)\b", "IT Software", "43230000"),
    (r"\b(consult|advisory|professional service|engagement|sow)\b", "Professional Services", "80101500"),
    (r"\b(freight|logistics|shipping|haulage|courier|ltl|ftl)\b", "Freight & Logistics", "78101800"),
    (r"\b(valve|bearing|seal|pump|gasket|fitting|mro|spare)\b", "MRO & Industrial", "40141600"),
    (r"\b(chemical|solvent|reagent|lubricant|coating)\b", "Raw Materials", "12160000"),
    (r"\b(packag|corrugat|carton|pallet|shrink|tape)\b", "Packaging", "24111500"),
    (r"\b(clean|janitor|facilit|hvac|maintenance|grounds)\b", "Facilities", "76111500"),
    (r"\b(staff|contractor|temp|agency|labour|labor|recruit)\b", "Contingent Labour", "80111600"),
    (r"\b(print|catalog|brochure|marketing|advertis|media)\b", "Marketing", "82121500"),
    (r"\b(travel|hotel|airfare|flight|mileage)\b", "Travel", "90121500"),
    (r"\b(train|course|certification|seminar|conference)\b", "Training", "86132000"),
    (r"\b(legal|counsel|attorney|law firm)\b", "Legal", "80121600"),
    (r"\b(insur|premium|broker|underwrit)\b", "Insurance", "84131500"),
    (r"\b(utilit|electric|gas supply|water|telecom|broadband)\b", "Utilities", "83101500"),
    (r"\b(stationer|office suppl|consumable|toner|paper)\b", "Office Supplies", "44120000"),
    (r"\b(ppe|safety|glove|helmet|goggle|protective)\b", "Safety Equipment", "46180000"),
    (r"\b(cater|food|refreshment|hospitality)\b", "Catering", "90101500"),
    (r"\b(research|market study|analytics|survey|benchmark)\b", "Research & Analytics", "80101600"),
    (r"\b(courier|same-?day|next-?day delivery)\b", "Freight & Logistics", "78101800"),
]


def classify(description: str, supplier_name: str = "", *, hint_category: str | None = None) -> dict:
    """Classify one transaction. Returns the matched token so it is explainable."""
    haystack = f"{description} {supplier_name}".lower()

    for pattern, category, unspsc in TAXONOMY:
        match = re.search(pattern, haystack)
        if match:
            # Description matches are stronger evidence than supplier-name matches.
            in_description = bool(re.search(pattern, (description or "").lower()))
            return {
                "category": category,
                "unspsc": unspsc,
                "confidence": 0.94 if in_description else 0.82,
                "matched_on": match.group(0),
                "basis": "description" if in_description else "supplier name",
            }

    if hint_category:
        return {"category": hint_category, "unspsc": None, "confidence": 0.60,
                "matched_on": None, "basis": "supplier master category"}

    return {"category": None, "unspsc": None, "confidence": 0.0,
            "matched_on": None, "basis": "no taxonomy match"}


def normalize_suppliers(raw_names: list[str], master: list[dict], *, threshold: float = 0.82) -> dict:
    """Resolve raw supplier strings to master records and cluster duplicates."""
    resolutions: dict[str, dict] = {}
    unresolved: list[str] = []

    for raw in {n for n in raw_names if n}:
        best, best_score = None, 0.0
        for supplier in master:
            score = max(
                text_similarity(raw, supplier.get("name", "")),
                text_similarity(raw, supplier.get("legal_name") or ""),
            )
            if score > best_score:
                best, best_score = supplier, score
        if best and best_score >= threshold:
            resolutions[raw] = {"supplier_id": best["id"], "name": best["name"],
                                "score": round(best_score, 4)}
        else:
            unresolved.append(raw)
            if best:
                resolutions[raw] = {"supplier_id": None, "candidate": best["name"],
                                    "score": round(best_score, 4)}

    # Two raw strings resolving to the same master record are a duplicate cluster.
    clusters: dict[str, list[str]] = defaultdict(list)
    for raw, res in resolutions.items():
        if res.get("supplier_id"):
            clusters[res["supplier_id"]].append(raw)
    duplicates = [
        {"supplier_id": sid, "variants": sorted(variants)}
        for sid, variants in clusters.items() if len(variants) > 1
    ]

    return {
        "resolutions": resolutions,
        "unresolved": unresolved,
        "duplicate_clusters": duplicates,
        "resolved_pct": round(
            len([r for r in resolutions.values() if r.get("supplier_id")])
            / max(1, len(resolutions)) * 100, 1),
        "requires_human_review": bool(unresolved),
    }


def detect_maverick(transactions: list[dict], *, contracted_suppliers: set[str],
                    preferred_categories: set[str] | None = None) -> dict:
    """Off-contract spend, measured by value."""
    preferred_categories = preferred_categories or set()
    maverick, compliant = [], []
    for txn in transactions:
        amount = float(txn.get("amount_usd") or 0.0)
        on_contract = bool(txn.get("on_contract")) or txn.get("supplier_id") in contracted_suppliers
        has_po = bool(txn.get("po_number"))
        if on_contract and has_po:
            compliant.append(txn)
        else:
            reasons = []
            if not on_contract:
                reasons.append("supplier not under contract")
            if not has_po:
                reasons.append("no purchase order")
            maverick.append({**txn, "maverick_reasons": reasons})

    total = sum(float(t.get("amount_usd") or 0.0) for t in transactions) or 1.0
    maverick_value = sum(float(t.get("amount_usd") or 0.0) for t in maverick)
    return {
        "maverick_transactions": maverick,
        "maverick_count": len(maverick),
        "maverick_spend_usd": round(maverick_value, 2),
        "total_spend_usd": round(total, 2),
        "contract_compliance_pct": round((1 - maverick_value / total) * 100, 2),
        "requires_human_review": maverick_value > 0,
    }


# Indicative realisable rates by lever — stated openly so the number can be argued with.
LEVER_RATES = {
    "consolidation": 0.08,
    "contract_coverage": 0.06,
    "volume_discount": 0.04,
    "vendor_rationalization": 0.05,
    "demand_management": 0.10,
}


def identify_savings(*, by_category: dict[str, dict], duplicate_clusters: list[dict],
                     maverick_spend: float, uncontracted_by_category: dict[str, float]) -> dict:
    """Turn spend structure into a priced opportunity list."""
    opportunities: list[dict] = []

    for cluster in duplicate_clusters:
        spend = float(cluster.get("spend_usd") or 0.0)
        if spend < 25_000:
            continue
        rate = LEVER_RATES["vendor_rationalization"]
        opportunities.append({
            "title": f"Rationalise {len(cluster['variants'])} duplicate records for "
                     f"{cluster.get('name', 'supplier')}",
            "lever": "vendor_rationalization",
            "category": cluster.get("category"),
            "supplier_id": cluster.get("supplier_id"),
            "annual_spend_usd": round(spend, 2),
            "estimated_savings_usd": round(spend * rate, 2),
            "confidence": 0.82,
            "rationale": f"Spend is split across variants {', '.join(cluster['variants'][:4])}, "
                         f"which fragments negotiating leverage. Consolidating typically "
                         f"realises {rate:.0%}.",
        })

    for category, spend in uncontracted_by_category.items():
        if spend < 40_000:
            continue
        rate = LEVER_RATES["contract_coverage"]
        opportunities.append({
            "title": f"Bring {category} under contract",
            "lever": "contract_coverage",
            "category": category,
            "annual_spend_usd": round(spend, 2),
            "estimated_savings_usd": round(spend * rate, 2),
            "confidence": 0.78,
            "rationale": f"{spend:,.0f} USD of {category} spend has no contract coverage. "
                         f"Competitive coverage typically returns {rate:.0%}.",
        })

    for category, stats in by_category.items():
        spend = float(stats.get("spend_usd") or 0.0)
        suppliers = int(stats.get("supplier_count") or 0)
        if spend >= 150_000 and suppliers >= 3:
            rate = LEVER_RATES["consolidation"]
            opportunities.append({
                "title": f"Consolidate {category} across {suppliers} suppliers",
                "lever": "consolidation",
                "category": category,
                "annual_spend_usd": round(spend, 2),
                "estimated_savings_usd": round(spend * rate, 2),
                "confidence": 0.80,
                "rationale": f"{suppliers} suppliers serve {spend:,.0f} USD of {category}. "
                             f"Consolidating to one or two typically returns {rate:.0%}.",
            })

    if maverick_spend >= 50_000:
        rate = LEVER_RATES["demand_management"]
        opportunities.append({
            "title": "Redirect maverick spend to contracted channels",
            "lever": "demand_management",
            "annual_spend_usd": round(maverick_spend, 2),
            "estimated_savings_usd": round(maverick_spend * rate, 2),
            "confidence": 0.72,
            "rationale": f"{maverick_spend:,.0f} USD was bought off-contract. Channel "
                         f"enforcement typically recovers {rate:.0%} of that value.",
        })

    opportunities.sort(key=lambda o: o["estimated_savings_usd"], reverse=True)
    total = round(sum(o["estimated_savings_usd"] for o in opportunities), 2)
    return {
        "opportunities": opportunities,
        "total_estimated_savings_usd": total,
        "lever_rates": LEVER_RATES,
        "requires_human_review": True,
    }
