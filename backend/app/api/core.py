"""Core P2P resources: invoices, suppliers, POs, contracts, exceptions,
approvals, payments, purchase requests and supplier correspondence."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..agents.orchestrator import orchestrator
from ..database import get_db
from ..enums import (
    ApprovalStatus,
    EventType,
    ExceptionStatus,
    InvoiceStatus,
    PaymentStatus,
    SLAStatus,
    WorkflowStage,
)
from ..models import (
    Approval,
    Contract,
    ExceptionCase,
    Invoice,
    InvoiceLine,
    Payment,
    PurchaseOrder,
    PurchaseRequest,
    Supplier,
    SupplierMessage,
    User,
    utcnow,
)
from ..serializers import (
    approval_out,
    contract_out,
    exception_out,
    execution_out,
    human_task_out,
    invoice_out,
    message_out,
    payment_out,
    po_out,
    purchase_request_out,
    supplier_out,
    user_out,
)
from ..services.audit import write_audit
from ..services.events import record_event
from ..services.metrics import supplier_scorecard
from .deps import get_current_user, require_controller, require_manager

router = APIRouter(tags=["p2p"])


# ==========================================================================
# Invoices
# ==========================================================================
class InvoiceLineIn(BaseModel):
    line_number: int = 1
    item_code: str | None = None
    description: str = ""
    uom: str = "EA"
    quantity: float = 0.0
    unit_price: float = 0.0


class InvoiceIn(BaseModel):
    invoice_number: str
    supplier_name: str
    po_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str = "USD"
    subtotal: float | None = None
    tax_amount: float = 0.0
    freight_amount: float = 0.0
    total_amount: float | None = None
    source_channel: str = "portal"
    document_text: str | None = None
    lines: list[InvoiceLineIn] = Field(default_factory=list)
    run_agent: bool = True


@router.get("/invoices")
def list_invoices(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    status: str | None = None,
    stage: str | None = None,
    supplier_id: str | None = None,
    sla_status: str | None = None,
    search: str | None = None,
    include_closed: bool = False,
    limit: int = 200,
) -> dict:
    query = select(Invoice).order_by(Invoice.received_at.desc())
    if status:
        query = query.where(Invoice.status == status)
    if stage:
        query = query.where(Invoice.stage == stage)
    if supplier_id:
        query = query.where(Invoice.supplier_id == supplier_id)
    if sla_status:
        query = query.where(Invoice.sla_status == sla_status)
    if not include_closed:
        query = query.where(Invoice.stage != WorkflowStage.CLOSED)
    if search:
        term = f"%{search.lower()}%"
        query = query.where(
            func.lower(Invoice.invoice_number).like(term)
            | func.lower(Invoice.supplier_name_raw).like(term)
        )
    invoices = db.execute(query.limit(limit)).scalars().all()
    return {"count": len(invoices), "items": [invoice_out(i) for i in invoices]}


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    return invoice_out(invoice, detail=True, db=db)


@router.get("/invoices/{invoice_id}/timeline")
def invoice_timeline(
    invoice_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    from ..models import AgentExecution, AuditLog, HumanTask, WorkflowEvent
    from ..serializers import audit_out, event_out

    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")

    events = db.execute(
        select(WorkflowEvent).where(WorkflowEvent.entity_id == invoice_id)
        .order_by(WorkflowEvent.created_at.asc())
    ).scalars().all()
    runs = db.execute(
        select(AgentExecution).where(AgentExecution.entity_id == invoice_id)
        .order_by(AgentExecution.created_at.asc())
    ).scalars().all()
    tasks = db.execute(
        select(HumanTask).where(HumanTask.entity_id == invoice_id)
        .order_by(HumanTask.created_at.asc())
    ).scalars().all()
    audits = db.execute(
        select(AuditLog).where(AuditLog.entity_id == invoice_id)
        .order_by(AuditLog.timestamp.asc())
    ).scalars().all()

    return {
        "invoice": invoice_out(invoice, detail=True, db=db),
        "events": [event_out(e) for e in events],
        "agent_runs": [execution_out(r, detail=True) for r in runs],
        "checkpoints": [human_task_out(t, detail=True) for t in tasks],
        "audit": [audit_out(a) for a in audits],
    }


@router.post("/invoices/process", status_code=201)
def process_invoice(
    payload: InvoiceIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Ingest an invoice and hand it to the Invoice Intake Agent.

    The agent will analyse it and stop at a human checkpoint — the invoice
    never self-advances.
    """
    lines = payload.lines or []
    subtotal = payload.subtotal
    if subtotal is None:
        subtotal = round(sum(l.quantity * l.unit_price for l in lines), 2)
    total = payload.total_amount
    if total is None:
        total = round(subtotal + payload.tax_amount + payload.freight_amount, 2)

    invoice_date = payload.invoice_date or date.today()
    due_date = payload.due_date or (invoice_date + timedelta(days=30))

    document = payload.document_text
    if not document:
        from ..seed import render_document

        document = render_document(
            supplier_name=payload.supplier_name,
            invoice_number=payload.invoice_number,
            invoice_date=invoice_date,
            due_date=due_date,
            po_number=payload.po_number,
            lines=[
                {
                    "line_number": l.line_number, "item_code": l.item_code or "",
                    "description": l.description, "uom": l.uom,
                    "quantity": l.quantity, "unit_price": l.unit_price,
                    "line_total": round(l.quantity * l.unit_price, 2),
                }
                for l in lines
            ],
            subtotal=subtotal, tax=payload.tax_amount, freight=payload.freight_amount,
            total=total, currency=payload.currency,
        )

    invoice = Invoice(
        invoice_number=payload.invoice_number,
        supplier_name_raw=payload.supplier_name,
        po_number_raw=payload.po_number,
        invoice_date=invoice_date,
        due_date=due_date,
        currency=payload.currency,
        subtotal=subtotal,
        tax_amount=payload.tax_amount,
        freight_amount=payload.freight_amount,
        total_amount=total,
        amount_usd=total,
        source_channel=payload.source_channel,
        document_text=document,
        status=InvoiceStatus.RECEIVED,
        stage=WorkflowStage.INTAKE,
        sla_due_at=utcnow() + timedelta(hours=24),
        sla_status=SLAStatus.ON_TRACK,
    )
    db.add(invoice)
    db.flush()

    for line in lines:
        db.add(InvoiceLine(
            invoice_id=invoice.id,
            line_number=line.line_number,
            item_code=line.item_code,
            description=line.description,
            uom=line.uom,
            quantity=line.quantity,
            unit_price=line.unit_price,
            line_total=round(line.quantity * line.unit_price, 2),
        ))
    db.flush()

    record_event(
        db, event_type=EventType.INVOICE_RECEIVED,
        title=f"Invoice received · {payload.source_channel.upper()}",
        message=f"{payload.invoice_number} from {payload.supplier_name} "
                f"({payload.currency} {total:,.2f})",
        entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
        actor=user.full_name, actor_type="human",
    )
    write_audit(
        db, action="invoice.received", description=f"Invoice {payload.invoice_number} ingested via "
                                                   f"{payload.source_channel}.",
        actor=user.full_name, actor_type="human", actor_role=user.role,
        entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
        after_state={"total": total, "currency": payload.currency},
    )

    response: dict = {"invoice": invoice_out(invoice, detail=True, db=db)}
    if payload.run_agent:
        results = orchestrator.advance_invoice(db, invoice.id, triggered_by=user.full_name)
        response["runs"] = [execution_out(r.execution, detail=True) for r in results]
        response["checkpoints"] = [human_task_out(t, detail=True) for r in results for t in r.tasks]
    db.commit()
    response["invoice"] = invoice_out(db.get(Invoice, invoice.id), detail=True, db=db)
    return response


@router.post("/invoices/upload", status_code=201)
async def upload_invoice(
    file: UploadFile = File(...),
    supplier_name: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Accept a text-based invoice document (txt / eml / csv-like) and run intake.

    Binary PDFs are accepted but only their embedded text is used; the demo's
    extraction skill is deterministic and text-driven by design.
    """
    raw = await file.read()
    try:
        text = raw.decode("utf-8", errors="ignore")
    except Exception:  # pragma: no cover
        text = ""

    from ..skills import invoice_extraction

    extraction = invoice_extraction.extract(text, channel="scan" if file.filename.lower().endswith(
        (".png", ".jpg", ".jpeg", ".tif", ".tiff")) else "pdf")
    fields = extraction["fields"]

    invoice = Invoice(
        invoice_number=fields.get("invoice_number") or f"UPLOAD-{utcnow():%Y%m%d%H%M%S}",
        supplier_name_raw=supplier_name or fields.get("supplier_name") or "Unknown supplier",
        po_number_raw=fields.get("po_number"),
        invoice_date=fields.get("invoice_date"),
        due_date=fields.get("due_date"),
        currency=fields.get("currency") or "USD",
        subtotal=fields.get("subtotal") or 0.0,
        tax_amount=fields.get("tax_amount") or 0.0,
        freight_amount=fields.get("freight_amount") or 0.0,
        total_amount=fields.get("total_amount") or 0.0,
        amount_usd=fields.get("total_amount") or 0.0,
        source_channel="scan" if file.filename.lower().endswith(
            (".png", ".jpg", ".jpeg", ".tif", ".tiff")) else "pdf",
        source_filename=file.filename,
        document_text=text,
        extraction_confidence=extraction["confidence"],
        extraction_fields={k: str(v) for k, v in fields.items()},
        status=InvoiceStatus.RECEIVED,
        stage=WorkflowStage.INTAKE,
        sla_due_at=utcnow() + timedelta(hours=24),
    )
    db.add(invoice)
    db.flush()
    record_event(
        db, event_type=EventType.INVOICE_RECEIVED,
        title=f"Document uploaded · {file.filename}",
        message=f"Extracted at {extraction['confidence']:.0%} header confidence.",
        entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
        actor=user.full_name, actor_type="human",
    )
    results = orchestrator.advance_invoice(db, invoice.id, triggered_by=user.full_name)
    db.commit()
    return {
        "invoice": invoice_out(db.get(Invoice, invoice.id), detail=True, db=db),
        "extraction": {k: str(v) for k, v in extraction.items() if k != "fields"},
        "checkpoints": [human_task_out(t, detail=True) for r in results for t in r.tasks],
    }


# ==========================================================================
# Suppliers
# ==========================================================================
@router.get("/suppliers")
def list_suppliers(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    rows = db.execute(select(Supplier).order_by(Supplier.name)).scalars().all()
    return {"count": len(rows), "items": [supplier_out(s) for s in rows]}


@router.get("/suppliers/scorecard")
def scorecard(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[dict]:
    return supplier_scorecard(db)


@router.get("/suppliers/{supplier_id}")
def get_supplier(supplier_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    invoices = db.execute(
        select(Invoice).where(Invoice.supplier_id == supplier_id)
        .order_by(Invoice.received_at.desc()).limit(30)
    ).scalars().all()
    contracts = db.execute(
        select(Contract).where(Contract.supplier_id == supplier_id)
    ).scalars().all()
    messages = db.execute(
        select(SupplierMessage).where(SupplierMessage.supplier_id == supplier_id)
        .order_by(SupplierMessage.created_at.desc()).limit(30)
    ).scalars().all()
    from ..skills import vendor_risk

    return {
        **supplier_out(supplier, detail=True),
        "risk_assessment": vendor_risk.assess(supplier),
        "invoices": [invoice_out(i) for i in invoices],
        "contracts": [contract_out(c) for c in contracts],
        "messages": [message_out(m) for m in messages],
    }


# ==========================================================================
# Purchase orders & contracts
# ==========================================================================
@router.get("/purchase-orders")
def list_pos(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    rows = db.execute(select(PurchaseOrder).order_by(PurchaseOrder.po_number)).scalars().all()
    return {"count": len(rows), "items": [po_out(p, detail=False) for p in rows]}


@router.get("/purchase-orders/{po_id}")
def get_po(po_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    po = db.get(PurchaseOrder, po_id)
    if po is None:
        raise HTTPException(status_code=404, detail="Purchase order not found.")
    return po_out(po)


@router.get("/contracts")
def list_contracts(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    rows = db.execute(select(Contract).order_by(Contract.contract_number)).scalars().all()
    return {"count": len(rows), "items": [contract_out(c) for c in rows]}


# ==========================================================================
# Exceptions
# ==========================================================================
@router.get("/exceptions")
def list_exceptions(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    status: str | None = Query(default="open_only"),
    exception_type: str | None = None,
    severity: str | None = None,
) -> dict:
    query = select(ExceptionCase).order_by(ExceptionCase.created_at.desc())
    if status == "open_only":
        query = query.where(
            ExceptionCase.status.notin_([ExceptionStatus.RESOLVED, ExceptionStatus.WRITTEN_OFF])
        )
    elif status and status != "all":
        query = query.where(ExceptionCase.status == status)
    if exception_type:
        query = query.where(ExceptionCase.exception_type == exception_type)
    if severity:
        query = query.where(ExceptionCase.severity == severity)
    rows = db.execute(query).scalars().all()
    return {
        "count": len(rows),
        "exposure": round(sum(r.financial_impact_usd or 0.0 for r in rows), 2),
        "items": [exception_out(r) for r in rows],
    }


@router.get("/exceptions/{exception_id}")
def get_exception(exception_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    case = db.get(ExceptionCase, exception_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Exception not found.")
    data = exception_out(case)
    data["invoice"] = invoice_out(case.invoice, detail=True, db=db) if case.invoice else None
    return data


# ==========================================================================
# Approvals
# ==========================================================================
@router.get("/approvals")
def list_approvals(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    mine_only: bool = False,
    status: str | None = "pending",
) -> dict:
    query = select(Approval).order_by(Approval.requested_at.asc())
    if status and status != "all":
        query = query.where(Approval.status == status)
    if mine_only:
        query = query.where(Approval.approver_id == user.id)
    rows = db.execute(query).scalars().all()
    return {"count": len(rows), "items": [approval_out(a, db) for a in rows]}


class ApprovalDecision(BaseModel):
    approved: bool
    notes: str | None = None


@router.post("/approvals/{approval_id}/decide")
def decide_approval(
    approval_id: str,
    payload: ApprovalDecision,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """A human approver acting on the invoice itself (distinct from approving an
    agent's proposal — this is the business approval)."""
    approval = db.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found.")
    if approval.status not in {ApprovalStatus.PENDING, ApprovalStatus.DELEGATED, ApprovalStatus.ESCALATED}:
        raise HTTPException(status_code=409, detail="This approval has already been decided.")

    invoice = db.get(Invoice, approval.invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if approval.approver_id != user.id and user.approval_limit_usd < (invoice.total_amount or 0.0):
        raise HTTPException(
            status_code=403,
            detail="You are not the assigned approver and your limit does not cover this invoice.",
        )

    before = {"status": approval.status, "invoice_status": invoice.status}
    approval.status = ApprovalStatus.APPROVED if payload.approved else ApprovalStatus.REJECTED
    approval.decided_at = utcnow()
    approval.decision_notes = payload.notes
    invoice.human_touches = (invoice.human_touches or 0) + 1

    approver = db.get(User, approval.approver_id) if approval.approver_id else None
    if approver is not None:
        approver.active_workload = max(0, (approver.active_workload or 0) - 1)

    if payload.approved:
        invoice.status = InvoiceStatus.APPROVED
        invoice.stage = WorkflowStage.PAYMENT
    else:
        invoice.status = InvoiceStatus.REJECTED
        invoice.stage = WorkflowStage.REJECTED
        invoice.closed_at = utcnow()

    record_event(
        db, event_type=EventType.APPROVAL_DECIDED,
        title="Invoice " + ("approved" if payload.approved else "rejected"),
        message=f"{invoice.invoice_number} {'approved' if payload.approved else 'rejected'} by "
                f"{user.full_name}." + (f" {payload.notes}" if payload.notes else ""),
        entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
        actor=user.full_name, actor_type="human",
        severity="success" if payload.approved else "warning",
    )
    write_audit(
        db, action="approval.decided",
        description=f"{user.full_name} {'approved' if payload.approved else 'rejected'} "
                    f"{invoice.invoice_number} ({invoice.currency} {invoice.total_amount:,.2f}).",
        actor=user.full_name, actor_type="human", actor_role=user.role,
        entity_type="invoice", entity_id=invoice.id, entity_label=invoice.invoice_number,
        before_state=before, after_state={"status": invoice.status},
    )
    db.commit()
    return approval_out(db.get(Approval, approval_id), db)


# ==========================================================================
# Payments
# ==========================================================================
@router.get("/payments")
def list_payments(
    db: Session = Depends(get_db), _: User = Depends(get_current_user), status: str | None = None
) -> dict:
    query = select(Payment).order_by(Payment.created_at.desc())
    if status:
        query = query.where(Payment.status == status)
    rows = db.execute(query.limit(200)).scalars().all()
    return {
        "count": len(rows),
        "scheduled_value": round(
            sum(p.amount or 0.0 for p in rows if p.status == PaymentStatus.SCHEDULED), 2
        ),
        "discount_captured": round(sum(p.discount_captured or 0.0 for p in rows), 2),
        "items": [payment_out(p) for p in rows],
    }


# ==========================================================================
# Purchase requests
# ==========================================================================
class PurchaseRequestIn(BaseModel):
    description: str
    amount: float
    category: str | None = None
    supplier_id: str | None = None
    cost_center: str | None = None
    needed_by: date | None = None


@router.get("/purchase-requests")
def list_purchase_requests(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    rows = db.execute(
        select(PurchaseRequest).order_by(PurchaseRequest.created_at.desc())
    ).scalars().all()
    return {"count": len(rows), "items": [purchase_request_out(r) for r in rows]}


@router.post("/purchase-requests", status_code=201)
def create_purchase_request(
    payload: PurchaseRequestIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    from ..agents.registry import get_agent

    count = db.execute(select(func.count(PurchaseRequest.id))).scalar_one() or 0
    request = PurchaseRequest(
        request_number=f"PR-{count + 3001}",
        requester_id=user.id,
        requester_name=user.full_name,
        supplier_id=payload.supplier_id,
        description=payload.description,
        category=payload.category,
        amount=payload.amount,
        cost_center=payload.cost_center,
        needed_by=payload.needed_by,
        status="submitted",
    )
    db.add(request)
    db.flush()

    agent = get_agent("procurement_request")
    result = agent.run(db, {"request_id": request.id}, trigger="submission", triggered_by=user.full_name)
    db.commit()
    return {
        "request": purchase_request_out(db.get(PurchaseRequest, request.id)),
        "run": execution_out(result.execution, detail=True),
        "checkpoints": [human_task_out(t, detail=True) for t in result.tasks],
    }


# ==========================================================================
# Supplier correspondence
# ==========================================================================
class SupplierMessageIn(BaseModel):
    supplier_id: str
    body: str
    channel: str = "portal"
    invoice_id: str | None = None
    run_agent: bool = True


@router.get("/supplier-messages")
def list_messages(
    db: Session = Depends(get_db), _: User = Depends(get_current_user), supplier_id: str | None = None
) -> dict:
    query = select(SupplierMessage).order_by(SupplierMessage.created_at.desc())
    if supplier_id:
        query = query.where(SupplierMessage.supplier_id == supplier_id)
    rows = db.execute(query.limit(120)).scalars().all()
    return {"count": len(rows), "items": [message_out(m) for m in rows]}


@router.post("/supplier/chat", status_code=201)
def supplier_chat(
    payload: SupplierMessageIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Simulate an inbound supplier enquiry and let the Supplier Experience
    Agent draft the reply. The reply is not sent until a human releases it."""
    from ..agents.registry import get_agent

    supplier = db.get(Supplier, payload.supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found.")

    message = SupplierMessage(
        supplier_id=supplier.id,
        invoice_id=payload.invoice_id,
        channel=payload.channel,
        direction="inbound",
        author=f"{supplier.name} (supplier portal)",
        body=payload.body,
        status="received",
    )
    db.add(message)
    db.flush()
    record_event(
        db, event_type=EventType.SUPPLIER_MESSAGE,
        title=f"Supplier enquiry · {payload.channel}",
        message=payload.body[:180],
        entity_type="supplier", entity_id=supplier.id, entity_label=supplier.name,
        actor=supplier.name, actor_type="system",
    )

    response: dict = {"message": message_out(message)}
    if payload.run_agent:
        agent = get_agent("supplier_experience")
        result = agent.run(db, {"message_id": message.id}, trigger="inbound_message",
                           triggered_by=user.full_name)
        message.status = "answered_draft"
        response["run"] = execution_out(result.execution, detail=True)
        response["checkpoints"] = [human_task_out(t, detail=True) for t in result.tasks]
    db.commit()
    return response


# ==========================================================================
# People
# ==========================================================================
@router.get("/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[dict]:
    rows = db.execute(select(User).order_by(User.full_name)).scalars().all()
    return [user_out(u) for u in rows]


class OOOUpdate(BaseModel):
    out_of_office: bool
    days: int = 5


@router.patch("/users/{user_id}/out-of-office")
def set_ooo(
    user_id: str,
    payload: OOOUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_manager),
) -> dict:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    target.out_of_office = payload.out_of_office
    target.ooo_until = (utcnow() + timedelta(days=payload.days)) if payload.out_of_office else None
    write_audit(
        db, action="user.out_of_office",
        description=f"{actor.full_name} set {target.full_name} "
                    f"{'out of office' if payload.out_of_office else 'available'}.",
        actor=actor.full_name, actor_type="human", actor_role=actor.role,
        entity_type="user", entity_id=target.id, entity_label=target.full_name,
        after_state={"out_of_office": target.out_of_office},
    )
    db.commit()
    return user_out(target)
