"""Tail spend skills — detection, catalog compliance, consolidation, spot buys."""
from __future__ import annotations

from collections import defaultdict

SKILL = {
    "name": "tail_spend_detection",
    "title": "Tail Spend Detection",
    "purpose": "Isolate the long tail — the transactions that are most of the volume and least of the value.",
    "inputs": ["classified spend", "supplier master", "contract coverage"],
    "output": ["tail_transactions", "tail_spend_usd", "one_time_vendors", "pareto_point"],
    "success_criteria": "Tail identified on a defensible Pareto cut, not an arbitrary threshold.",
    "failure_handling": "Findings are advisory until a human approves consolidation or enforcement.",
    "used_by": ["tail_spend"],
}

CATALOG = {
    "name": "catalog_compliance",
    "title": "Catalog Compliance",
    "purpose": "Detect off-catalog buying where a contracted catalog item already exists.",
    "inputs": ["spend transactions", "catalog"],
    "output": ["off_catalog_transactions", "substitutable_items", "price_delta_usd"],
    "success_criteria": "Every off-catalog flag names the catalog item it should have used.",
    "failure_handling": "No substitute found means no flag — a false positive costs credibility.",
    "used_by": ["tail_spend"],
}

CONSOLIDATION = {
    "name": "vendor_consolidation",
    "title": "Vendor Consolidation",
    "purpose": "Group fragmented category spend onto a preferred supplier and price the move.",
    "inputs": ["tail transactions", "preferred suppliers", "category"],
    "output": ["consolidation_clusters", "recommended_supplier", "savings_usd"],
    "success_criteria": "Recommendations name the target supplier and the spend being moved.",
    "failure_handling": "Categories with no qualified preferred supplier are reported, not forced.",
    "used_by": ["tail_spend"],
}

SPOT_BUY = {
    "name": "spot_buy_automation",
    "title": "Spot Buy Automation",
    "purpose": "Turn a repeated one-off purchase into a quick three-quote RFQ.",
    "inputs": ["tail transaction cluster", "supplier shortlist"],
    "output": ["rfq_document", "suggested_suppliers"],
    "success_criteria": "Spot buys above the threshold get competitive tension.",
    "failure_handling": "The RFQ is a draft; issuing it to suppliers needs approval.",
    "used_by": ["tail_spend"],
}

# The tail is where cumulative spend passes this share of the total.
PARETO_CUT = 0.80
CONSOLIDATION_RATE = 0.11
# Minimum cluster value worth an intervention.
CLUSTER_MATERIALITY = 4_000.0


def detect(transactions: list[dict]) -> dict:
    """Split spend into head and tail on a Pareto cut, by supplier."""
    if not transactions:
        return {"tail_transactions": [], "tail_spend_usd": 0.0, "head_spend_usd": 0.0,
                "one_time_vendors": [], "pareto_point": 0, "requires_human_review": False}

    by_supplier: dict[str, dict] = defaultdict(lambda: {"spend": 0.0, "count": 0, "txns": []})
    for txn in transactions:
        key = txn.get("supplier_raw") or txn.get("supplier_name") or "unknown"
        entry = by_supplier[key]
        entry["spend"] += float(txn.get("amount_usd") or 0.0)
        entry["count"] += 1
        entry["txns"].append(txn)

    ranked = sorted(by_supplier.items(), key=lambda kv: kv[1]["spend"], reverse=True)
    total = sum(v["spend"] for _, v in ranked) or 1.0

    cumulative = 0.0
    head_suppliers: set[str] = set()
    pareto_point = 0
    for index, (name, entry) in enumerate(ranked):
        if cumulative / total < PARETO_CUT:
            head_suppliers.add(name)
            cumulative += entry["spend"]
            pareto_point = index + 1
        else:
            break

    tail_txns, tail_spend = [], 0.0
    one_time = []
    for name, entry in ranked:
        if name in head_suppliers:
            continue
        tail_spend += entry["spend"]
        for txn in entry["txns"]:
            tail_txns.append({**txn, "tail_supplier": name})
        if entry["count"] == 1:
            one_time.append({"supplier": name, "spend_usd": round(entry["spend"], 2)})

    return {
        "tail_transactions": tail_txns,
        "tail_spend_usd": round(tail_spend, 2),
        "head_spend_usd": round(total - tail_spend, 2),
        "total_spend_usd": round(total, 2),
        "tail_share_pct": round(tail_spend / total * 100, 2),
        "tail_transaction_share_pct": round(len(tail_txns) / len(transactions) * 100, 2),
        "tail_supplier_count": len(ranked) - len(head_suppliers),
        "head_supplier_count": len(head_suppliers),
        "one_time_vendors": sorted(one_time, key=lambda v: v["spend_usd"], reverse=True)[:20],
        "pareto_point": pareto_point,
        "requires_human_review": tail_spend > 0,
    }


def consolidation_plan(tail_transactions: list[dict], preferred: dict[str, str]) -> dict:
    """Cluster the tail by category and price the move to a preferred supplier."""
    clusters: dict[str, dict] = defaultdict(
        lambda: {"spend": 0.0, "count": 0, "suppliers": set(), "category": None})

    for txn in tail_transactions:
        category = txn.get("category") or "Uncategorised"
        entry = clusters[category]
        entry["category"] = category
        entry["spend"] += float(txn.get("amount_usd") or 0.0)
        entry["count"] += 1
        entry["suppliers"].add(txn.get("tail_supplier") or txn.get("supplier_raw") or "unknown")

    findings = []
    for category, entry in clusters.items():
        # The tail is small by definition; a 15k floor hides every real cluster.
        if entry["spend"] < CLUSTER_MATERIALITY or len(entry["suppliers"]) < 2:
            continue
        target = preferred.get(category)
        savings = round(entry["spend"] * CONSOLIDATION_RATE, 2) if target else 0.0
        findings.append({
            "finding_type": "consolidation" if target else "no_preferred_supplier",
            "category": category,
            "supplier_names": sorted(entry["suppliers"]),
            "transaction_count": entry["count"],
            "spend_usd": round(entry["spend"], 2),
            "recommended_supplier": target,
            "consolidation_savings_usd": savings,
            "recommendation": (
                f"Move {entry['spend']:,.0f} USD of {category} from "
                f"{len(entry['suppliers'])} tail suppliers onto {target}, "
                f"projected {savings:,.0f} USD at a {CONSOLIDATION_RATE:.0%} rate."
                if target else
                f"{entry['spend']:,.0f} USD of {category} is fragmented across "
                f"{len(entry['suppliers'])} suppliers with no preferred supplier on file — "
                f"a sourcing event is the right next step."
            ),
        })

    findings.sort(key=lambda f: f["consolidation_savings_usd"], reverse=True)
    return {
        "findings": findings,
        "total_savings_usd": round(sum(f["consolidation_savings_usd"] for f in findings), 2),
        "consolidation_rate": CONSOLIDATION_RATE,
        "requires_human_review": bool(findings),
    }


def catalog_gaps(transactions: list[dict], catalog: list[dict]) -> dict:
    """Off-catalog buying where a catalog item would have served."""
    by_category: dict[str, list[dict]] = defaultdict(list)
    for item in catalog:
        by_category[(item.get("category") or "").lower()].append(item)

    gaps, delta = [], 0.0
    for txn in transactions:
        if txn.get("on_contract"):
            continue
        options = by_category.get((txn.get("category") or "").lower())
        if not options:
            continue  # no substitute → no flag; a false positive costs credibility
        cheapest = min(options, key=lambda i: float(i.get("unit_price") or 0.0))
        amount = float(txn.get("amount_usd") or 0.0)
        estimated = round(amount * 0.09, 2)
        delta += estimated
        gaps.append({
            "external_id": txn.get("external_id"),
            "description": txn.get("description"),
            "supplier": txn.get("supplier_raw"),
            "amount_usd": amount,
            "category": txn.get("category"),
            "catalog_item": cheapest.get("item_code"),
            "catalog_description": cheapest.get("description"),
            "estimated_saving_usd": estimated,
        })

    gaps.sort(key=lambda g: g["estimated_saving_usd"], reverse=True)
    return {
        "off_catalog": gaps,
        "off_catalog_count": len(gaps),
        "price_delta_usd": round(delta, 2),
        "requires_human_review": bool(gaps),
    }
