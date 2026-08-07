"""Demo dataset.

Builds a small but realistic AP shop: seven people, ten suppliers, contracts,
POs, receipts, and a set of invoices engineered so that every agent has
something meaningful to say and every exception type is represented.

Everything is deterministic and relative to "now", so the demo looks fresh
whenever it is reset.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .agents.registry import seed_agent_configs
from .enums import (
    EventType,
    InvoiceStatus,
    MatchResult,
    PaymentStatus,
    RiskLevel,
    Role,
    SLAStatus,
    WorkflowStage,
)
from .models import (
    Approval,
    Contract,
    Invoice,
    InvoiceLine,
    Payment,
    POLine,
    PurchaseOrder,
    PurchaseRequest,
    Receipt,
    Supplier,
    SupplierMessage,
    User,
    utcnow,
)
from .services.audit import write_audit
from .services.events import record_event
from .services.policy import seed_policies

RNG = random.Random(20260101)
TODAY = date.today()
NOW = utcnow()


def _d(days: int) -> date:
    return TODAY - timedelta(days=days)


def _t(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


# ==========================================================================
# Document rendering — gives the extraction skill something real to parse
# ==========================================================================
def render_document(
    *,
    supplier_name: str,
    invoice_number: str,
    invoice_date: date,
    due_date: date,
    po_number: str | None,
    lines: list[dict],
    subtotal: float,
    tax: float,
    freight: float,
    total: float,
    currency: str = "USD",
    address: str = "",
    degrade: bool = False,
) -> str:
    line_rows = "\n".join(
        f"  {ln['line_number']:>3}  {ln['item_code']:<12} {ln['description'][:38]:<38} "
        f"{ln['quantity']:>8.2f} {ln['uom']:<4} {ln['unit_price']:>12,.2f} {ln['line_total']:>14,.2f}"
        for ln in lines
    )
    text = f"""
{supplier_name.upper()}
{address}

                              I N V O I C E

Invoice Number: {invoice_number}
Invoice Date: {invoice_date.isoformat()}
Due Date: {due_date.isoformat()}
Purchase Order: {po_number or 'N/A'}
Currency: {currency}

Bill To:
Northwind Industrial Group
400 Corporate Drive, Chicago, IL 60601

  Ln  Item         Description                            Quantity  UOM     Unit Price      Line Total
  --  -----------  -------------------------------------- --------  ----  ------------  --------------
{line_rows}

                                                        Sub-Total: {subtotal:,.2f}
                                                              Tax: {tax:,.2f}
                                                          Freight: {freight:,.2f}
                                                      Total Due: {total:,.2f}

Remit payment per agreed terms. Questions: ap-support@{supplier_name.split()[0].lower()}.example
""".strip()

    if degrade:
        # Simulate OCR noise from a low-quality scan.
        swaps = {"0": "O", "1": "l", "5": "S", "8": "B"}
        chars = list(text)
        for index in range(0, len(chars), 47):
            if chars[index] in swaps:
                chars[index] = swaps[chars[index]]
        text = "".join(chars)
    return text


def _line(n: int, code: str, desc: str, qty: float, price: float, uom: str = "EA") -> dict:
    return {
        "line_number": n,
        "item_code": code,
        "description": desc,
        "uom": uom,
        "quantity": qty,
        "unit_price": price,
        "line_total": round(qty * price, 2),
    }


# ==========================================================================
# Seed
# ==========================================================================
def seed_all(db: Session, *, force: bool = False) -> dict:
    if not force and db.execute(select(Invoice).limit(1)).scalars().first() is not None:
        seed_policies(db)
        seed_agent_configs(db)
        db.commit()
        return {"seeded": False, "reason": "data already present"}

    seed_policies(db)
    seed_agent_configs(db)

    users = _seed_users(db)
    suppliers = _seed_suppliers(db)
    contracts = _seed_contracts(db, suppliers)
    pos = _seed_purchase_orders(db, suppliers, contracts, users)
    _seed_receipts(db, pos)
    db.flush()

    counts = _seed_invoices(db, suppliers, pos, users)
    _seed_history(db, suppliers, users)
    _seed_supplier_messages(db, suppliers)
    _seed_purchase_requests(db, suppliers, users)

    record_event(
        db,
        event_type=EventType.SYSTEM,
        title="Demo dataset loaded",
        message=f"{counts['invoices']} live invoices across {len(suppliers)} suppliers, "
                f"plus 30 days of settled history.",
        actor="System",
        actor_type="system",
    )
    write_audit(
        db,
        action="system.demo_seeded",
        description="Demo dataset provisioned.",
        actor="System",
        actor_type="system",
        entity_type="system",
        entity_label="P2P AgentOps",
    )
    db.commit()
    return {"seeded": True, **counts, "suppliers": len(suppliers), "users": len(users)}


def _seed_users(db: Session) -> dict[str, User]:
    specs = [
        ("priya.raman@northwind.example", "Priya Raman", Role.AP_CLERK, "AP Specialist", "Accounts Payable", 0, False),
        ("marcus.hale@northwind.example", "Marcus Hale", Role.AP_CLERK, "AP Specialist", "Accounts Payable", 0, False),
        ("dana.okafor@northwind.example", "Dana Okafor", Role.AP_MANAGER, "AP Manager", "Accounts Payable", 50_000, False),
        ("tomas.lindqvist@northwind.example", "Tomas Lindqvist", Role.AP_MANAGER, "AP Manager, EMEA", "Accounts Payable", 50_000, True),
        ("sasha.mbeki@northwind.example", "Sasha Mbeki", Role.CONTROLLER, "Financial Controller", "Finance", 500_000, False),
        ("ken.oyelaran@northwind.example", "Ken Oyelaran", Role.PROCUREMENT, "Procurement Lead", "Procurement", 250_000, False),
        ("rivka.stein@northwind.example", "Rivka Stein", Role.TREASURY, "Treasury Analyst", "Treasury", 250_000, False),
        ("elena.duarte@northwind.example", "Elena Duarte", Role.CFO, "Chief Financial Officer", "Executive", 5_000_000, False),
        ("system@northwind.example", "Platform Service Account", Role.ADMIN, "Automation", "IT", 0, False),
    ]
    users: dict[str, User] = {}
    for email, name, role, title, dept, limit, ooo in specs:
        user = User(
            email=email,
            full_name=name,
            role=role,
            title=title,
            department=dept,
            approval_limit_usd=float(limit),
            out_of_office=ooo,
            ooo_until=(NOW + timedelta(days=5)) if ooo else None,
            avatar_initials="".join(p[0] for p in name.split()[:2]).upper(),
            active_workload=0,
        )
        db.add(user)
        users[email.split("@")[0]] = user
    db.flush()

    # Delegation matrix: the OOO manager delegates to the available one.
    users["tomas.lindqvist"].delegate_id = users["dana.okafor"].id
    users["dana.okafor"].delegate_id = users["sasha.mbeki"].id
    users["priya.raman"].delegate_id = users["marcus.hale"].id
    db.flush()
    return users


def _seed_suppliers(db: Session) -> dict[str, Supplier]:
    specs = [
        # code, name, category, tier, terms, disc%, disc days, country, risk
        ("SUP-1001", "Vertex Industrial Supply Inc.", "MRO & Industrial", "platinum", "2/10 NET30", 2.0, 10, "United States", "clear"),
        ("SUP-1002", "Helios Logistics Group LLC", "Freight & Logistics", "gold", "NET45", 0.0, 0, "United States", "clear"),
        ("SUP-1003", "Northlake Facilities Services", "Facilities", "silver", "NET30", 0.0, 0, "United States", "clear"),
        ("SUP-1004", "Aurora Software Systems GmbH", "IT & Software", "gold", "NET30", 1.5, 15, "Germany", "clear"),
        ("SUP-1005", "Cascade Packaging Co.", "Packaging", "silver", "NET60", 0.0, 0, "United States", "clear"),
        ("SUP-1006", "Meridian Consulting Partners", "Professional Services", "gold", "NET30", 0.0, 0, "United Kingdom", "clear"),
        ("SUP-1007", "Bluewater Chemicals Ltd", "Raw Materials", "platinum", "2/10 NET45", 2.0, 10, "United States", "clear"),
        ("SUP-1008", "Trident Components SA", "Components", "bronze", "NET30", 0.0, 0, "Singapore", "review"),
        ("SUP-1009", "Pinnacle Staffing Solutions", "Contingent Labour", "silver", "NET30", 0.0, 0, "United States", "clear"),
        ("SUP-1010", "Kestrel Print & Media", "Marketing", "bronze", "NET30", 0.0, 0, "Canada", "clear"),
    ]
    suppliers: dict[str, Supplier] = {}
    for idx, (code, name, category, tier, terms, disc, disc_days, country, sanctions) in enumerate(specs):
        supplier = Supplier(
            code=code,
            name=name,
            legal_name=name,
            country=country,
            currency="EUR" if country == "Germany" else "GBP" if country == "United Kingdom" else "USD",
            category=category,
            tier=tier,
            payment_terms=terms,
            early_pay_discount_pct=disc,
            early_pay_discount_days=disc_days,
            contact_name=f"AP Team",
            contact_email=f"ap@{name.split()[0].lower()}.example",
            bank_account_last4=f"{4100 + idx * 7}",
            tax_id=f"{81 + idx}-{4400000 + idx * 137}",
            tax_form_status="valid",
            tax_form_expiry=_d(-320 + idx * 5),
            insurance_expiry=_d(-200 + idx * 11),
            sanctions_status=sanctions,
            sanctions_checked_at=NOW - timedelta(days=idx),
            risk_score=8.0 + idx * 1.5,
            risk_level=RiskLevel.LOW,
            spend_ytd_usd=round(180_000 + idx * 96_500, 2),
            invoice_count_ytd=24 + idx * 6,
            on_time_payment_pct=round(97.5 - idx * 0.9, 1),
        )
        db.add(supplier)
        suppliers[code] = supplier
    db.flush()

    # Deliberate risk scenarios the Supplier Risk Agent will surface.
    suppliers["SUP-1008"].sanctions_status = "review"
    suppliers["SUP-1008"].risk_score = 42.0
    suppliers["SUP-1008"].risk_level = RiskLevel.HIGH

    suppliers["SUP-1010"].bank_account_last4 = "9931"
    suppliers["SUP-1010"].bank_changed_at = NOW - timedelta(days=3)  # inside the freeze window
    suppliers["SUP-1010"].risk_score = 38.0
    suppliers["SUP-1010"].risk_level = RiskLevel.HIGH

    suppliers["SUP-1009"].tax_form_status = "missing"
    suppliers["SUP-1009"].tax_form_expiry = None
    suppliers["SUP-1005"].insurance_expiry = _d(12)   # lapsed 12 days ago
    suppliers["SUP-1003"].tax_form_expiry = _d(-20)   # expires in 20 days
    db.flush()
    return suppliers


def _seed_contracts(db: Session, suppliers: dict[str, Supplier]) -> dict[str, Contract]:
    specs = [
        ("CTR-2201", "SUP-1001", "Industrial MRO Supply Agreement", 730, 400,
         {"VLV-3400": 412.50, "BRG-8820": 96.00, "SEAL-220": 18.75, "PMP-1100": 2450.00},
         ["valve", "bearing", "seal", "pump", "freight"],
         [{"threshold_usd": 50000, "discount_pct": 1.5}]),
        ("CTR-2202", "SUP-1004", "Enterprise Software Licence & Support", 400, 30,
         {"LIC-ENT": 185.00, "SUP-PREM": 42.00},
         ["licence", "license", "support", "subscription"],
         []),
        ("CTR-2203", "SUP-1006", "Management Consulting Master Services", 500, 120,
         {"CON-SR": 285.00, "CON-JR": 165.00, "CON-PM": 225.00},
         ["consulting", "advisory", "project management"],
         []),
        ("CTR-2204", "SUP-1007", "Bulk Chemical Supply Agreement", 600, 250,
         {"CHM-4420": 1180.00, "CHM-2210": 640.00},
         ["chemical", "solvent", "freight"],
         [{"threshold_usd": 75000, "discount_pct": 2.0}]),
        ("CTR-2205", "SUP-1002", "Freight & Logistics Services", 300, -15,  # expired 15 days ago
         {"FRT-LTL": 340.00, "FRT-FTL": 1850.00, "FRT-EXP": 720.00},
         ["freight", "logistics", "fuel surcharge"],
         []),
    ]
    contracts: dict[str, Contract] = {}
    for number, supplier_code, title, start_days_ago, end_days_ahead, rates, allowed, tiers in specs:
        contract = Contract(
            contract_number=number,
            supplier_id=suppliers[supplier_code].id,
            title=title,
            start_date=_d(start_days_ago),
            end_date=TODAY + timedelta(days=end_days_ahead),
            currency=suppliers[supplier_code].currency,
            total_value=round(250_000 + RNG.random() * 750_000, 2),
            payment_terms=suppliers[supplier_code].payment_terms,
            rate_card=rates,
            allowed_charges=allowed,
            volume_discounts=tiers,
            status="active" if end_days_ahead > 0 else "expired",
        )
        db.add(contract)
        contracts[number] = contract
    db.flush()
    return contracts


def _seed_purchase_orders(
    db: Session, suppliers: dict[str, Supplier], contracts: dict[str, Contract], users: dict[str, User]
) -> dict[str, PurchaseOrder]:
    specs = [
        ("PO-44210", "SUP-1001", "CTR-2201", "Q3 industrial valve and bearing replenishment", "CC-4400", "605100",
         [("VLV-3400", "3-inch stainless gate valve", 40, 412.50),
          ("BRG-8820", "Precision roller bearing 88mm", 120, 96.00),
          ("SEAL-220", "PTFE seal ring 220 series", 300, 18.75)], "SAP_S4HANA"),
        ("PO-44211", "SUP-1002", "CTR-2205", "Inbound freight — Midwest lanes, September", "CC-5100", "612300",
         [("FRT-LTL", "LTL shipment, zone 4", 26, 340.00),
          ("FRT-FTL", "Full truckload, Chicago-Dallas", 6, 1850.00)], "SAP_S4HANA"),
        ("PO-44212", "SUP-1004", "CTR-2202", "Enterprise licence renewal — 240 seats", "CC-7200", "641000",
         [("LIC-ENT", "Enterprise platform licence, annual", 240, 185.00),
          ("SUP-PREM", "Premium support, per seat", 240, 42.00)], "ORACLE_FUSION"),
        ("PO-44213", "SUP-1007", "CTR-2204", "Bulk solvent order — batch 4420", "CC-3300", "601200",
         [("CHM-4420", "Industrial solvent, 200L drum", 60, 1180.00),
          ("CHM-2210", "Cleaning agent, 200L drum", 25, 640.00)], "SAP_S4HANA"),
        ("PO-44214", "SUP-1006", "CTR-2203", "Supply chain optimisation engagement, phase 2", "CC-1100", "655000",
         [("CON-SR", "Senior consultant, hourly", 320, 285.00),
          ("CON-PM", "Engagement manager, hourly", 80, 225.00)], "COUPA"),
        ("PO-44215", "SUP-1003", None, "Facilities maintenance — Q3 scheduled service", "CC-2200", "618400",
         [("FAC-HVAC", "HVAC quarterly service visit", 12, 1450.00),
          ("FAC-JAN", "Janitorial service, monthly", 3, 6800.00)], "SAP_S4HANA"),
        ("PO-44216", "SUP-1005", None, "Corrugated packaging replenishment", "CC-4400", "605300",
         [("PKG-CRG", "Corrugated case, 24x18x12", 8000, 2.35),
          ("PKG-TAPE", "Sealing tape, 48mm x 100m", 400, 4.10)], "SAP_S4HANA"),
        ("PO-44217", "SUP-1009", None, "Contingent warehouse labour — September", "CC-4500", "607100",
         [("LAB-WH", "Warehouse associate, hourly", 960, 28.50)], "SAP_S4HANA"),
        ("PO-44218", "SUP-1010", None, "Product catalogue print run — autumn", "CC-8100", "660200",
         [("PRT-CAT", "Catalogue, 64pp full colour", 15000, 1.28)], "ARIBA"),
        ("PO-44219", "SUP-1008", None, "Precision component order — assembly line 3", "CC-3300", "602100",
         [("CMP-7710", "Machined housing, spec 7710", 500, 74.20)], "SAP_S4HANA"),
    ]
    pos: dict[str, PurchaseOrder] = {}
    for index, (number, supplier_code, contract_number, description, cc, gl, lines, erp) in enumerate(specs):
        supplier = suppliers[supplier_code]
        po = PurchaseOrder(
            po_number=number,
            supplier_id=supplier.id,
            contract_id=contracts[contract_number].id if contract_number else None,
            description=description,
            cost_center=cc,
            gl_account=gl,
            requester_id=users["marcus.hale"].id if index % 2 else users["priya.raman"].id,
            buyer_id=users["ken.oyelaran"].id,
            currency=supplier.currency,
            status="open",
            order_date=_d(45 - index * 2),
            erp_system=erp,
        )
        db.add(po)
        db.flush()
        total = 0.0
        for line_no, (code, desc, qty, price) in enumerate(lines, start=1):
            line_total = round(qty * price, 2)
            total += line_total
            db.add(POLine(
                po_id=po.id, line_number=line_no, item_code=code, description=desc,
                uom="HR" if code.startswith(("CON-", "LAB-")) else "EA",
                quantity=qty, unit_price=price, line_total=line_total,
                received_qty=qty, invoiced_qty=0.0,
            ))
        po.total_amount = round(total, 2)
        po.received_amount = round(total, 2)
        pos[number] = po
    db.flush()

    # Scenario: nothing has been received against PO-44216 yet.
    for line in pos["PO-44216"].lines:
        line.received_qty = 0.0
    pos["PO-44216"].received_amount = 0.0
    db.flush()
    return pos


def _seed_receipts(db: Session, pos: dict[str, PurchaseOrder]) -> None:
    for index, (number, po) in enumerate(pos.items()):
        if number == "PO-44216":  # deliberately un-received
            continue
        lines = [
            {
                "po_line_id": line.id,
                "item_code": line.item_code,
                "description": line.description,
                "quantity": line.received_qty,
                "unit_price": line.unit_price,
            }
            for line in po.lines
        ]
        db.add(Receipt(
            receipt_number=f"GR-{7100 + index}",
            po_id=po.id,
            received_date=_d(20 - index),
            received_by="Warehouse Receiving",
            total_quantity=sum(l["quantity"] for l in lines),
            total_value=round(sum(l["quantity"] * l["unit_price"] for l in lines), 2),
            lines_json=lines,
            status="posted",
        ))
    db.flush()


def _make_invoice(
    db: Session,
    *,
    supplier: Supplier,
    po: PurchaseOrder | None,
    invoice_number: str,
    lines: list[dict],
    tax_rate: float = 0.0,
    freight: float = 0.0,
    received_hours_ago: float = 2.0,
    channel: str = "pdf",
    terms_days: int = 30,
    degrade: bool = False,
    tax_override: float | None = None,
    total_override: float | None = None,
    stage: str = WorkflowStage.INTAKE,
    status: str = InvoiceStatus.RECEIVED,
    supplier_name_override: str | None = None,
    po_number_override: str | None = "",
    resolve_supplier: bool = True,
    resolve_po: bool = True,
) -> Invoice:
    subtotal = round(sum(l["line_total"] for l in lines), 2)
    tax = round(subtotal * tax_rate, 2) if tax_override is None else tax_override
    total = round(subtotal + tax + freight, 2) if total_override is None else total_override
    invoice_date = (NOW - timedelta(hours=received_hours_ago)).date() - timedelta(days=1)
    due_date = invoice_date + timedelta(days=terms_days)
    po_number = po.po_number if po else None
    if po_number_override != "":
        po_number = po_number_override

    document = render_document(
        supplier_name=supplier_name_override or supplier.name,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        due_date=due_date,
        po_number=po_number,
        lines=lines,
        subtotal=subtotal,
        tax=tax,
        freight=freight,
        total=total,
        currency=supplier.currency,
        address=f"{supplier.country}",
        degrade=degrade,
    )

    invoice = Invoice(
        invoice_number=invoice_number,
        # Captured at intake as a real AP system would; the Invoice Intake Agent
        # still re-verifies it and asks a human to confirm before anything moves.
        supplier_id=supplier.id if resolve_supplier else None,
        supplier_name_raw=supplier_name_override or supplier.name,
        po_id=po.id if (po is not None and resolve_po) else None,
        po_number_raw=po_number,
        invoice_date=invoice_date,
        due_date=due_date,
        received_at=_t(received_hours_ago),
        currency=supplier.currency,
        subtotal=subtotal,
        tax_amount=tax,
        freight_amount=freight,
        total_amount=total,
        amount_usd=total,
        source_channel=channel,
        source_filename=f"{invoice_number.replace('/', '-')}.pdf",
        document_text=document,
        status=status,
        stage=stage,
        sla_due_at=_t(received_hours_ago) + timedelta(hours=24),
        sla_status=SLAStatus.ON_TRACK,
    )
    db.add(invoice)
    db.flush()
    for line in lines:
        db.add(InvoiceLine(
            invoice_id=invoice.id,
            line_number=line["line_number"],
            item_code=line["item_code"],
            description=line["description"],
            uom=line["uom"],
            quantity=line["quantity"],
            unit_price=line["unit_price"],
            line_total=line["line_total"],
            tax_rate=tax_rate * 100,
        ))
    db.flush()

    record_event(
        db,
        event_type=EventType.INVOICE_RECEIVED,
        title=f"Invoice received · {channel.upper()}",
        message=f"{invoice_number} from {supplier_name_override or supplier.name} "
                f"({supplier.currency} {total:,.2f})",
        entity_type="invoice",
        entity_id=invoice.id,
        entity_label=invoice_number,
        actor="Intake channel",
        actor_type="system",
    )
    return invoice


def _seed_invoices(
    db: Session, suppliers: dict[str, Supplier], pos: dict[str, PurchaseOrder], users: dict[str, User]
) -> dict:
    created: list[Invoice] = []

    # 1 — Clean three-way match. The happy path, still human-confirmed.
    created.append(_make_invoice(
        db, supplier=suppliers["SUP-1001"], po=pos["PO-44210"], invoice_number="VIS-2026-08841",
        lines=[_line(1, "VLV-3400", "3-inch stainless gate valve", 40, 412.50),
               _line(2, "BRG-8820", "Precision roller bearing 88mm", 120, 96.00),
               _line(3, "SEAL-220", "PTFE seal ring 220 series", 300, 18.75)],
        tax_rate=0.0875, received_hours_ago=1.5, channel="edi", terms_days=30,
    ))

    # 2 — Price variance above tolerance (rate increase not agreed).
    created.append(_make_invoice(
        db, supplier=suppliers["SUP-1007"], po=pos["PO-44213"], invoice_number="BWC-449021",
        lines=[_line(1, "CHM-4420", "Industrial solvent, 200L drum", 60, 1274.40),   # +8% vs 1180.00
               _line(2, "CHM-2210", "Cleaning agent, 200L drum", 25, 640.00)],
        tax_rate=0.06, received_hours_ago=6, channel="pdf", terms_days=45,
    ))

    # 3 — Missing goods receipt.
    created.append(_make_invoice(
        db, supplier=suppliers["SUP-1005"], po=pos["PO-44216"], invoice_number="CSP-77120",
        lines=[_line(1, "PKG-CRG", "Corrugated case, 24x18x12", 8000, 2.35),
               _line(2, "PKG-TAPE", "Sealing tape, 48mm x 100m", 400, 4.10)],
        tax_rate=0.07, received_hours_ago=14, channel="email", terms_days=60,
    ))

    # 4 — Low-confidence scan with an unresolvable supplier name variant.
    created.append(_make_invoice(
        db, supplier=suppliers["SUP-1003"], po=pos["PO-44215"], invoice_number="NFS-3391-B",
        lines=[_line(1, "FAC-HVAC", "HVAC quarterly service visit", 4, 1450.00),
               _line(2, "FAC-JAN", "Janitorial service, monthly", 1, 6800.00)],
        tax_rate=0.0, received_hours_ago=9, channel="scan", degrade=True, terms_days=30,
        supplier_name_override="Northlake Fac. Svcs",
        resolve_supplier=False, resolve_po=False,
    ))

    # 5 — Contract rate breach plus an unauthorised charge.
    created.append(_make_invoice(
        db, supplier=suppliers["SUP-1006"], po=pos["PO-44214"], invoice_number="MCP-INV-5540",
        lines=[_line(1, "CON-SR", "Senior consultant, hourly", 320, 312.00, "HR"),   # contract 285.00
               _line(2, "CON-PM", "Engagement manager, hourly", 80, 225.00, "HR"),
               _line(3, "MISC-EXP", "Administrative surcharge", 1, 4800.00)],        # not an allowed charge
        tax_rate=0.20, received_hours_ago=20, channel="portal", terms_days=30,
    ))

    # 6 — Tax that does not reconcile.
    created.append(_make_invoice(
        db, supplier=suppliers["SUP-1004"], po=pos["PO-44212"], invoice_number="ASG-DE-99120",
        lines=[_line(1, "LIC-ENT", "Enterprise platform licence, annual", 240, 185.00),
               _line(2, "SUP-PREM", "Premium support, per seat", 240, 42.00)],
        tax_override=13_602.00,   # ~24.9% — outside the 7-19% German band
        received_hours_ago=4, channel="pdf", terms_days=30,
    ))

    # 7 — No PO reference at all.
    created.append(_make_invoice(
        db, supplier=suppliers["SUP-1009"], po=None, invoice_number="PSS-2026-1187",
        lines=[_line(1, "LAB-WH", "Warehouse associate, hourly", 320, 28.50, "HR")],
        tax_rate=0.0, received_hours_ago=11, channel="email", terms_days=30,
        po_number_override=None,
    ))

    # 8 — Expired contract pricing (freight agreement lapsed).
    created.append(_make_invoice(
        db, supplier=suppliers["SUP-1002"], po=pos["PO-44211"], invoice_number="HLG-88-40213",
        lines=[_line(1, "FRT-LTL", "LTL shipment, zone 4", 26, 368.00),   # +8.2% vs expired 340.00
               _line(2, "FRT-FTL", "Full truckload, Chicago-Dallas", 6, 1850.00)],
        tax_rate=0.0, freight=0.0, received_hours_ago=14, channel="edi", terms_days=45,
    ))

    # 9 — Supplier under sanctions review.
    created.append(_make_invoice(
        db, supplier=suppliers["SUP-1008"], po=pos["PO-44219"], invoice_number="TCS-SG-4402",
        lines=[_line(1, "CMP-7710", "Machined housing, spec 7710", 500, 74.20)],
        tax_rate=0.09, received_hours_ago=16, channel="portal", terms_days=30,
    ))

    # 10 — Supplier with a fresh bank change (payment freeze scenario).
    created.append(_make_invoice(
        db, supplier=suppliers["SUP-1010"], po=pos["PO-44218"], invoice_number="KPM-CA-7781",
        lines=[_line(1, "PRT-CAT", "Catalogue, 64pp full colour", 15000, 1.28)],
        tax_rate=0.05, received_hours_ago=19, channel="email", terms_days=30,
    ))

    # 11 — Duplicate of invoice #1, arriving on a different channel.
    created.append(_make_invoice(
        db, supplier=suppliers["SUP-1001"], po=pos["PO-44210"], invoice_number="VIS-2026-08841",
        lines=[_line(1, "VLV-3400", "3-inch stainless gate valve", 40, 412.50),
               _line(2, "BRG-8820", "Precision roller bearing 88mm", 120, 96.00),
               _line(3, "SEAL-220", "PTFE seal ring 220 series", 300, 18.75)],
        tax_rate=0.0875, received_hours_ago=0.5, channel="email", terms_days=30,
    ))

    # ---- Aged invoice already sitting in an approval queue ---------------
    aged = _make_invoice(
        db, supplier=suppliers["SUP-1001"], po=pos["PO-44210"], invoice_number="VIS-2026-08702",
        lines=[_line(1, "PMP-1100", "Centrifugal pump, 1100 series", 6, 2450.00),
               _line(2, "SEAL-220", "PTFE seal ring 220 series", 100, 18.75)],
        tax_rate=0.0875, received_hours_ago=79, channel="edi", terms_days=30,
        stage=WorkflowStage.APPROVAL, status=InvoiceStatus.PENDING_APPROVAL,
    )
    aged.supplier_id = suppliers["SUP-1001"].id
    aged.po_id = pos["PO-44210"].id
    aged.match_result = MatchResult.MATCHED
    aged.extraction_confidence = 0.99
    aged.approver_id = users["tomas.lindqvist"].id   # who is out of office
    aged.sla_status = SLAStatus.AT_RISK
    aged.sla_risk_score = 78.0
    db.add(Approval(
        invoice_id=aged.id,
        approver_id=users["tomas.lindqvist"].id,
        original_approver_id=users["tomas.lindqvist"].id,
        level=1,
        requested_at=_t(76),
        due_at=_t(76) + timedelta(hours=24),
        reminders_sent=1,
        last_reminder_at=_t(40),
        routing_reason="Routed on value; EMEA cost centre owner.",
    ))
    users["tomas.lindqvist"].active_workload = 7
    created.append(aged)

    # ---- Approved and ERP-posted, waiting on a payment decision ----------
    for index, (code, po_key, number, lines, hours, tier_note) in enumerate([
        ("SUP-1001", "PO-44210", "VIS-2026-08655",
         [_line(1, "BRG-8820", "Precision roller bearing 88mm", 200, 96.00)], 20, "2/10 discount live"),
        ("SUP-1007", "PO-44213", "BWC-448870",
         [_line(1, "CHM-2210", "Cleaning agent, 200L drum", 40, 640.00)], 23, "2/10 discount live"),
        ("SUP-1006", "PO-44214", "MCP-INV-5488",
         [_line(1, "CON-JR", "Consultant, hourly", 240, 165.00, "HR")], 26, "NET30"),
    ]):
        supplier = suppliers[code]
        invoice = _make_invoice(
            db, supplier=supplier, po=pos[po_key], invoice_number=number, lines=lines,
            tax_rate=0.0875 if supplier.currency == "USD" else 0.20,
            received_hours_ago=hours, channel="edi", terms_days=30,
            stage=WorkflowStage.PAYMENT, status=InvoiceStatus.APPROVED,
        )
        invoice.supplier_id = supplier.id
        invoice.po_id = pos[po_key].id
        invoice.match_result = MatchResult.MATCHED
        invoice.extraction_confidence = 0.99
        invoice.erp_document_number = f"51{90000000 + index * 137}"
        invoice.erp_posted_at = _t(hours - 6)
        invoice.due_date = TODAY + timedelta(days=2 + index * 4)
        invoice.invoice_date = TODAY - timedelta(days=8)
        invoice.human_touches = 1
        created.append(invoice)

    db.flush()
    return {"invoices": len(created)}


def _seed_history(db: Session, suppliers: dict[str, Supplier], users: dict[str, User]) -> None:
    """Thirty days of settled invoices so the KPI tiles have a real baseline."""
    codes = list(suppliers)
    for index in range(42):
        supplier = suppliers[codes[index % len(codes)]]
        received = NOW - timedelta(days=RNG.randint(3, 30), hours=RNG.randint(0, 20))
        # Weighted so the historical baseline reads like a real AP shop:
        # mostly inside SLA, with a visible tail of slow ones.
        cycle = round(RNG.uniform(3.0, 22.0) if RNG.random() < 0.88 else RNG.uniform(26.0, 90.0), 2)
        paid_at = received + timedelta(hours=cycle)
        amount = round(RNG.uniform(1_800, 68_000), 2)
        touchless = RNG.random() < 0.58
        invoice = Invoice(
            invoice_number=f"HIST-{9000 + index}",
            supplier_id=supplier.id,
            supplier_name_raw=supplier.name,
            invoice_date=received.date(),
            due_date=(received + timedelta(days=30)).date(),
            received_at=received,
            currency=supplier.currency,
            subtotal=round(amount * 0.92, 2),
            tax_amount=round(amount * 0.08, 2),
            total_amount=amount,
            amount_usd=amount,
            source_channel=RNG.choice(["edi", "pdf", "email", "portal"]),
            status=InvoiceStatus.PAID,
            stage=WorkflowStage.CLOSED,
            match_result=MatchResult.MATCHED,
            extraction_confidence=round(RNG.uniform(0.93, 0.995), 3),
            touchless=touchless,
            human_touches=0 if touchless else RNG.randint(1, 3),
            sla_due_at=received + timedelta(hours=24),
            sla_status=SLAStatus.MET if cycle <= 24 else SLAStatus.BREACHED,
            paid_at=paid_at,
            closed_at=paid_at,
            cycle_time_hours=cycle,
            erp_document_number=f"51{80000000 + index * 91}",
            erp_posted_at=received + timedelta(hours=cycle * 0.7),
        )
        db.add(invoice)
        db.flush()
        db.add(Payment(
            payment_number=f"PAY-{8000 + index}",
            invoice_id=invoice.id,
            supplier_id=supplier.id,
            amount=amount,
            currency=supplier.currency,
            discount_captured=round(amount * 0.02, 2) if supplier.early_pay_discount_pct and touchless else 0.0,
            method="ACH",
            scheduled_date=paid_at.date(),
            released_at=paid_at,
            released_by=users["rivka.stein"].full_name,
            status=PaymentStatus.PAID,
            priority_score=round(RNG.uniform(30, 80), 1),
        ))
    db.flush()


def _seed_supplier_messages(db: Session, suppliers: dict[str, Supplier]) -> None:
    threads = [
        ("SUP-1005", "portal", "Cascade Packaging AP",
         "Hi — could you tell me the status of invoice CSP-77120? It was submitted last week and we "
         "haven't seen it move. When will it be paid?"),
        ("SUP-1009", "email", "Pinnacle Staffing Billing",
         "Following up on invoice PSS-2026-1187. Is anything missing from our submission? "
         "It appears to be on hold."),
        ("SUP-1010", "email", "Kestrel Print Accounts",
         "Please update our remittance details — we have changed banks. New account information "
         "attached. Confirm once the change is applied."),
        ("SUP-1001", "teams", "Vertex Industrial AP",
         "Quick question on payment date for VIS-2026-08655 — are we still on the 2/10 discount?"),
    ]
    for code, channel, author, body in threads:
        db.add(SupplierMessage(
            supplier_id=suppliers[code].id,
            channel=channel,
            direction="inbound",
            author=author,
            body=body,
            status="received",
        ))
    db.flush()


def _seed_purchase_requests(
    db: Session, suppliers: dict[str, Supplier], users: dict[str, User]
) -> None:
    specs = [
        ("PR-3001", "Priya Raman", "SUP-1003", "Replacement HVAC filters for Plant 2", "Facilities", 3_450.00),
        ("PR-3002", "Marcus Hale", "SUP-1004", "Additional 40 software seats for the finance team", "IT & Software", 9_080.00),
        ("PR-3003", "Ken Oyelaran", "SUP-1006", "Phase 3 supply chain advisory engagement", "Professional Services", 148_000.00),
    ]
    for number, requester, supplier_code, description, category, amount in specs:
        db.add(PurchaseRequest(
            request_number=number,
            requester_name=requester,
            supplier_id=suppliers[supplier_code].id,
            description=description,
            category=category,
            amount=amount,
            needed_by=TODAY + timedelta(days=21),
            cost_center="CC-2200",
            status="submitted",
        ))
    db.flush()
