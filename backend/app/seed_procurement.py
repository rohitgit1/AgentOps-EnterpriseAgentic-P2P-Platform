"""Procurement AgentOps demo dataset.

Adds the strategic layer on top of the P2P demo: a spend cube to analyse, a
sourcing event mid-flight with bids to score, and — importantly — a set of
**sample input attachments** already in the library, so a demo can show an agent
consuming a real file rather than talking about one.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .enums import EventType
from .models import (
    Contract,
    SourcingBid,
    SourcingEvent,
    SpendTransaction,
    Supplier,
    User,
    utcnow,
)
from .services import artifacts as artifact_service
from .services.events import record_event

RNG = random.Random(770420)
TODAY = date.today()

# Raw supplier strings deliberately include variants of the same vendor, so
# supplier normalisation has real duplicates to collapse.
SPEND_TEMPLATES: list[tuple[str, str, float, float]] = [
    ("Vertex Industrial Supply Inc.", "Replacement gate valve, 3-inch stainless", 400, 4200),
    ("Vertex Industrial Supply", "Roller bearing assembly, spare", 350, 2600),
    ("VERTEX INDUSTRIAL SUPPLY INC", "PTFE seal ring, bulk pack", 180, 1400),
    ("Helios Logistics Group LLC", "LTL freight, zone 4 shipment", 320, 2800),
    ("Helios Logistics", "Expedited courier delivery", 240, 900),
    ("Aurora Software Systems GmbH", "Enterprise platform licence renewal", 4000, 22000),
    ("Aurora Software Systems", "Premium support subscription", 900, 4800),
    ("Northlake Facilities Services", "HVAC quarterly maintenance visit", 900, 3200),
    ("Northlake Facilities Svcs", "Janitorial service, monthly", 2200, 7400),
    ("Cascade Packaging Co.", "Corrugated cases, bulk", 700, 5200),
    ("Bluewater Chemicals Ltd", "Industrial solvent drum", 1100, 9800),
    ("Meridian Consulting Partners", "Advisory engagement, senior consultant", 6000, 42000),
    ("Pinnacle Staffing Solutions", "Warehouse contractor hours", 900, 6400),
    ("Kestrel Print & Media", "Product catalogue print run", 700, 5100),
    ("Trident Components SA", "Machined housing, spec 7710", 1400, 8600),
    ("QuickShip Courier", "Same-day courier, one-off", 90, 420),
    ("Metro Office Supplies", "Stationery and consumables", 60, 380),
    ("BrightSpark Electrical", "Emergency electrical callout", 400, 1800),
    ("Apex Safety Gear", "PPE replenishment, non-catalog", 250, 1600),
    ("Riverbend Catering", "Site catering, quarterly review", 300, 1500),
    ("Summit Travel Services", "Airfare and hotel, project team", 800, 4200),
    ("Nova Training Institute", "Certification course, four seats", 600, 3200),
    ("Halcyon Legal LLP", "External counsel, contract review", 2500, 14000),
    ("PrimeCare Insurance Brokers", "Broker fee, annual renewal", 1800, 9000),
    ("Vantage Analytics", "One-off market study", 1200, 7800),
]

CATALOG_CSV = """item_code,description,category,unit_price
CAT-PPE-001,Safety glasses ANSI Z87.1 (box of 12),MRO & Industrial,84.00
CAT-PPE-002,Nitrile gloves size L (case of 1000),MRO & Industrial,132.50
CAT-STA-010,A4 copier paper (box of 5 reams),Facilities,42.00
CAT-STA-011,Toner cartridge black high yield,Facilities,118.00
CAT-FRT-100,LTL shipment zone 4 (contracted rate),Freight & Logistics,312.00
CAT-FRT-101,Same-day courier metro (contracted rate),Freight & Logistics,78.00
CAT-MRO-220,PTFE seal ring 220 series,MRO & Industrial,18.75
CAT-MRO-221,Roller bearing 88mm precision,MRO & Industrial,96.00
"""

REQUIREMENTS_BRIEF = """# Requirements brief — Regional freight & logistics, FY27

## Background

Our current freight agreement (CTR-2205) lapsed and we are buying at list rates
across three carriers. Annual spend in this category is approximately 850,000 USD
with volume concentrated on Midwest lanes.

## Scope of requirement

- Provide LTL and FTL road freight across our Midwest distribution network
- Handle approximately 4,200 units of shipment volume per year
- Guarantee 98% on-time-in-full delivery measured monthly
- Provide a dedicated account manager and quarterly business reviews
- Supply EDI 214 shipment status messages into our TMS
- Offer a fixed rate card for a 24 month term with no fuel surcharge escalators
- Provide certificate of insurance to 5,000,000 USD before first shipment

## Commercial parameters

Budget not to exceed 850,000 USD annually. Rates must be fixed for the initial
24 month term. Payment terms NET45 or better.

## Compliance requirements

Suppliers must hold current cargo liability insurance, complete our supplier
code of conduct attestation, and pass restricted-party screening before award.
"""

BID_RESPONSES_CSV = """supplier_name,bid_amount_usd,lead_time_days,technical_score,risk_score
Helios Logistics Group LLC,798000,21,86,18
Vertex Industrial Supply Inc.,845000,28,72,12
Cascade Packaging Co.,912000,35,64,26
Trident Components SA,762000,45,79,44
"""

CREDIT_REPORT_CSV = """supplier,credit_rating,days_beyond_terms,bankruptcy_flag
Vertex Industrial Supply Inc.,A,4,false
Helios Logistics Group LLC,BBB,11,false
Northlake Facilities Services,BB,22,false
Aurora Software Systems GmbH,A,2,false
Cascade Packaging Co.,BB,18,false
Meridian Consulting Partners,BBB,7,false
Bluewater Chemicals Ltd,AA,3,false
Trident Components SA,CCC,41,true
Pinnacle Staffing Solutions,B,29,false
Kestrel Print & Media,BB,16,false
"""

OTIF_CSV = """supplier,otif_pct,capacity_utilisation_pct,single_source
Vertex Industrial Supply Inc.,97,72,false
Helios Logistics Group LLC,91,88,false
Northlake Facilities Services,84,64,true
Aurora Software Systems GmbH,99,55,true
Cascade Packaging Co.,88,93,false
Meridian Consulting Partners,95,70,false
Bluewater Chemicals Ltd,96,81,true
Trident Components SA,73,96,true
Pinnacle Staffing Solutions,86,90,false
Kestrel Print & Media,90,60,false
"""

THIRD_PARTY_MSA = """# MASTER SERVICES AGREEMENT

This Agreement is entered into between the Customer and Trident Components SA
("Supplier").

## 1. Services
Supplier shall provide machined components as ordered by Customer from time to
time.

## 2. Pricing
Supplier may adjust the price of any item upon thirty (30) days notice to
Customer. Prices quoted are indicative only.

## 3. Term
This Agreement shall commence on the Effective Date and shall automatically
renew for successive twelve (12) month periods.

## 4. Liability
Customer shall indemnify Supplier against any and all claims arising from the
use of the components, without limitation as to amount.

## 5. Confidentiality
Each party shall keep confidential the other party's proprietary information.

## 6. Governing law
This Agreement is governed by the laws of Singapore and the parties submit to
the exclusive jurisdiction of the courts of Singapore.

## 7. Delivery
Supplier shall deliver components in accordance with agreed schedules and shall
provide 95% on-time delivery performance.
"""


def seed_procurement(db: Session, *, force: bool = False) -> dict:
    """Layer the procurement demo on top of the P2P dataset."""
    if not force and db.execute(select(SpendTransaction).limit(1)).scalars().first() is not None:
        return {"seeded": False, "reason": "procurement data already present"}

    suppliers = {s.name: s for s in db.execute(select(Supplier)).scalars().all()}
    users = {u.role: u for u in db.execute(select(User)).scalars().all()}

    counts = {
        "spend_transactions": _seed_spend(db, suppliers),
        "sourcing_events": _seed_sourcing(db, suppliers, users),
        "sample_attachments": _seed_attachments(db, users),
    }

    record_event(
        db,
        event_type=EventType.SYSTEM,
        title="Procurement dataset loaded",
        message=f"{counts['spend_transactions']} spend transactions, "
                f"{counts['sourcing_events']} sourcing event(s), "
                f"{counts['sample_attachments']} sample input attachment(s) ready for agents.",
        actor="System", actor_type="system",
    )
    db.commit()
    return {"seeded": True, **counts}


def _seed_spend(db: Session, suppliers: dict[str, Supplier]) -> int:
    """Build a spend cube with duplicates, maverick buying and a real tail."""
    created = 0
    for index in range(340):
        name, description, low, high = SPEND_TEMPLATES[index % len(SPEND_TEMPLATES)]
        amount = round(RNG.uniform(low, high), 2)
        supplier = suppliers.get(name)

        # Head suppliers mostly buy on contract with a PO; the tail mostly does not.
        is_tail_vendor = name in {
            "QuickShip Courier", "Metro Office Supplies", "BrightSpark Electrical",
            "Apex Safety Gear", "Riverbend Catering", "Summit Travel Services",
            "Nova Training Institute", "Halcyon Legal LLP", "PrimeCare Insurance Brokers",
            "Vantage Analytics",
        }
        on_contract = (not is_tail_vendor) and RNG.random() < 0.78
        has_po = on_contract or RNG.random() < 0.35

        db.add(SpendTransaction(
            external_id=f"TXN-{100000 + index}",
            supplier_raw=name,
            supplier_id=supplier.id if supplier else None,
            description=description,
            amount_usd=amount,
            transaction_date=TODAY - timedelta(days=RNG.randint(1, 270)),
            cost_center=RNG.choice(["CC-1100", "CC-2200", "CC-3300", "CC-4400", "CC-5100", "CC-8100"]),
            po_number=f"PO-{44210 + RNG.randint(0, 9)}" if has_po else None,
            on_contract=on_contract,
        ))
        created += 1
    db.flush()
    return created


def _seed_sourcing(db: Session, suppliers: dict[str, Supplier], users: dict[str, User]) -> int:
    """One awarded event (so cycle-time reduction has a number) and one live
    event with bids waiting to be scored."""
    procurement_lead = users.get("procurement")

    awarded = SourcingEvent(
        event_number="SRC-9001",
        title="Industrial MRO consumables — annual agreement",
        category="MRO & Industrial",
        event_type="RFP",
        budget_usd=620_000.0,
        incumbent_spend_usd=655_000.0,
        requirements="Annual supply of valves, bearings and seals across three plants.",
        compliance_rules=["Cargo and liability insurance", "Supplier code of conduct"],
        weighting={"commercial": 0.45, "technical": 0.35, "risk": 0.20},
        status="awarded",
        owner_id=procurement_lead.id if procurement_lead else None,
        issued_at=utcnow() - timedelta(days=19),
        response_due=TODAY - timedelta(days=5),
        awarded_supplier_id=suppliers["Vertex Industrial Supply Inc."].id
        if "Vertex Industrial Supply Inc." in suppliers else None,
        awarded_at=utcnow() - timedelta(days=2),
        expected_savings_usd=71_500.0,
        cycle_days=17.0,
        baseline_cycle_days=56.0,
    )
    db.add(awarded)
    db.flush()
    for name, amount, lead, tech, risk, total, status in [
        ("Vertex Industrial Supply Inc.", 583_500.0, 14, 88, 12, 87.4, "awarded"),
        ("Trident Components SA", 561_000.0, 40, 74, 44, 74.9, "not_awarded"),
        ("Cascade Packaging Co.", 642_000.0, 25, 69, 26, 70.1, "not_awarded"),
    ]:
        db.add(SourcingBid(
            event_id=awarded.id,
            supplier_id=suppliers[name].id if name in suppliers else None,
            supplier_name=name, bid_amount_usd=amount, lead_time_days=lead,
            technical_score=tech, risk_score=risk, total_score=total, status=status,
        ))

    live = SourcingEvent(
        event_number="SRC-9002",
        title="Regional freight & logistics — FY27",
        category="Freight & Logistics",
        event_type="RFP",
        budget_usd=850_000.0,
        incumbent_spend_usd=903_000.0,
        requirements=REQUIREMENTS_BRIEF,
        compliance_rules=[
            "Cargo liability insurance to 5,000,000 USD",
            "Supplier code of conduct attestation",
            "Restricted-party screening clear before award",
        ],
        weighting={"commercial": 0.45, "technical": 0.35, "risk": 0.20},
        status="issued",
        owner_id=procurement_lead.id if procurement_lead else None,
        issued_at=utcnow() - timedelta(days=6),
        response_due=TODAY + timedelta(days=8),
        baseline_cycle_days=56.0,
    )
    db.add(live)
    db.flush()
    for name, amount, lead, tech, risk in [
        ("Helios Logistics Group LLC", 798_000.0, 21, 86, 18),
        ("Vertex Industrial Supply Inc.", 845_000.0, 28, 72, 12),
        ("Cascade Packaging Co.", 912_000.0, 35, 64, 26),
        ("Trident Components SA", 762_000.0, 45, 79, 44),
    ]:
        db.add(SourcingBid(
            event_id=live.id,
            supplier_id=suppliers[name].id if name in suppliers else None,
            supplier_name=name, bid_amount_usd=amount, lead_time_days=lead,
            technical_score=tech, risk_score=risk, status="received",
        ))
    db.flush()
    return 2


def _seed_attachments(db: Session, users: dict[str, User]) -> int:
    """Sample input files, ready in the library so a demo can run an agent
    against a real attachment immediately."""
    lead = users.get("procurement")
    author = lead.full_name if lead else "System"

    spend_rows = ["external_id,supplier,description,amount_usd,date,cost_center,po_number,on_contract"]
    for index in range(120):
        name, description, low, high = SPEND_TEMPLATES[index % len(SPEND_TEMPLATES)]
        amount = round(RNG.uniform(low, high), 2)
        on_contract = "true" if RNG.random() < 0.55 else "false"
        po = f"PO-{44210 + RNG.randint(0, 9)}" if on_contract == "true" else ""
        spend_rows.append(
            f"TXN-Q4-{200000 + index},{name},{description},{amount},"
            f"{(TODAY - timedelta(days=RNG.randint(1, 90))).isoformat()},"
            f"CC-{RNG.choice(['1100', '2200', '3300', '4400'])},{po},{on_contract}"
        )

    specs = [
        ("requirements-freight-fy27.md", "Requirements brief — Regional freight FY27",
         REQUIREMENTS_BRIEF, "requirements_brief"),
        ("bids-SRC-9002.csv", "Bid responses — SRC-9002 freight",
         BID_RESPONSES_CSV, "bid_responses"),
        ("spend-extract-q4.csv", "Spend extract — Q4 (120 transactions)",
         "\n".join(spend_rows) + "\n", "spend_extract"),
        ("catalog.csv", "Contracted catalog items", CATALOG_CSV, "catalog"),
        ("credit-report.csv", "Credit & financial distress indicators",
         CREDIT_REPORT_CSV, "financial_indicators"),
        ("otif-performance.csv", "Delivery performance (OTIF, capacity, single-source)",
         OTIF_CSV, "delivery_performance"),
        ("trident-msa-draft.md", "Third-party MSA — Trident Components (for review)",
         THIRD_PARTY_MSA, "contract_document"),
    ]
    for filename, title, content, kind in specs:
        artifact_service.store_input(
            db, filename=filename, content=content, title=title, kind=kind,
            uploaded_by=author, meta={"sample": True},
        )
    db.flush()
    return len(specs)
