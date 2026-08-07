"""SQLAlchemy models — the P2P system of record plus the agent control plane."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .enums import (
    AgentRunStatus,
    ApprovalStatus,
    AutonomyLevel,
    ExceptionStatus,
    HumanTaskStatus,
    InvoiceStatus,
    MatchResult,
    PaymentStatus,
    RiskLevel,
    Role,
    SLAStatus,
    WorkflowStage,
)


def _uuid() -> str:
    return uuid.uuid4().hex[:16]


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


# ===========================================================================
# People
# ===========================================================================
class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default=Role.AP_CLERK, index=True)
    department: Mapped[str | None] = mapped_column(String(120), nullable=True)
    title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    avatar_initials: Mapped[str | None] = mapped_column(String(4), nullable=True)
    approval_limit_usd: Mapped[float] = mapped_column(Float, default=0.0)
    out_of_office: Mapped[bool] = mapped_column(Boolean, default=False)
    ooo_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delegate_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"), nullable=True)
    active_workload: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    delegate = relationship("User", remote_side=[id], uselist=False)


# ===========================================================================
# Master data
# ===========================================================================
class Supplier(Base, TimestampMixin):
    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country: Mapped[str] = mapped_column(String(64), default="United States")
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tier: Mapped[str] = mapped_column(String(16), default="silver")  # platinum|gold|silver|bronze
    payment_terms: Mapped[str] = mapped_column(String(32), default="NET30")
    early_pay_discount_pct: Mapped[float] = mapped_column(Float, default=0.0)
    early_pay_discount_days: Mapped[int] = mapped_column(Integer, default=0)

    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    bank_account_last4: Mapped[str | None] = mapped_column(String(8), nullable=True)
    bank_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    tax_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tax_form_status: Mapped[str] = mapped_column(String(32), default="valid")  # valid|expiring|missing
    tax_form_expiry: Mapped[Date | None] = mapped_column(Date, nullable=True)
    insurance_expiry: Mapped[Date | None] = mapped_column(Date, nullable=True)
    sanctions_status: Mapped[str] = mapped_column(String(32), default="clear")  # clear|review|hit
    sanctions_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    risk_score: Mapped[float] = mapped_column(Float, default=12.0)  # 0-100, higher = riskier
    risk_level: Mapped[str] = mapped_column(String(16), default=RiskLevel.LOW)
    on_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    hold_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    spend_ytd_usd: Mapped[float] = mapped_column(Float, default=0.0)
    invoice_count_ytd: Mapped[int] = mapped_column(Integer, default=0)
    on_time_payment_pct: Mapped[float] = mapped_column(Float, default=95.0)

    invoices = relationship("Invoice", back_populates="supplier")
    contracts = relationship("Contract", back_populates="supplier")


class PurchaseOrder(Base, TimestampMixin):
    __tablename__ = "purchase_orders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    po_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    supplier_id: Mapped[str] = mapped_column(String(32), ForeignKey("suppliers.id"), index=True)
    contract_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("contracts.id"), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_center: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gl_account: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requester_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"), nullable=True)
    buyer_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)
    invoiced_amount: Mapped[float] = mapped_column(Float, default=0.0)
    received_amount: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="open")
    order_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    erp_system: Mapped[str] = mapped_column(String(32), default="SAP_S4HANA")

    supplier = relationship("Supplier")
    lines = relationship("POLine", back_populates="po", cascade="all, delete-orphan")
    receipts = relationship("Receipt", back_populates="po")


class POLine(Base):
    __tablename__ = "po_lines"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    po_id: Mapped[str] = mapped_column(String(32), ForeignKey("purchase_orders.id"), index=True)
    line_number: Mapped[int] = mapped_column(Integer, default=1)
    item_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    uom: Mapped[str] = mapped_column(String(16), default="EA")
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)
    line_total: Mapped[float] = mapped_column(Float, default=0.0)
    received_qty: Mapped[float] = mapped_column(Float, default=0.0)
    invoiced_qty: Mapped[float] = mapped_column(Float, default=0.0)

    po = relationship("PurchaseOrder", back_populates="lines")


class Receipt(Base, TimestampMixin):
    __tablename__ = "receipts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    receipt_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    po_id: Mapped[str] = mapped_column(String(32), ForeignKey("purchase_orders.id"), index=True)
    received_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    received_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    total_quantity: Mapped[float] = mapped_column(Float, default=0.0)
    total_value: Mapped[float] = mapped_column(Float, default=0.0)
    lines_json: Mapped[list | None] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="posted")

    po = relationship("PurchaseOrder", back_populates="receipts")


class Contract(Base, TimestampMixin):
    __tablename__ = "contracts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    contract_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    supplier_id: Mapped[str] = mapped_column(String(32), ForeignKey("suppliers.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    start_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    total_value: Mapped[float] = mapped_column(Float, default=0.0)
    payment_terms: Mapped[str] = mapped_column(String(32), default="NET30")
    rate_card: Mapped[dict | None] = mapped_column(JSON, default=dict)   # item_code -> agreed unit price
    allowed_charges: Mapped[list | None] = mapped_column(JSON, default=list)
    volume_discounts: Mapped[list | None] = mapped_column(JSON, default=list)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="active")

    supplier = relationship("Supplier", back_populates="contracts")


# ===========================================================================
# Transactions
# ===========================================================================
class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    invoice_number: Mapped[str] = mapped_column(String(80), index=True)
    supplier_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("suppliers.id"), index=True)
    supplier_name_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    po_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("purchase_orders.id"), nullable=True)
    po_number_raw: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contract_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("contracts.id"), nullable=True)

    invoice_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    subtotal: Mapped[float] = mapped_column(Float, default=0.0)
    tax_amount: Mapped[float] = mapped_column(Float, default=0.0)
    freight_amount: Mapped[float] = mapped_column(Float, default=0.0)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)
    amount_usd: Mapped[float] = mapped_column(Float, default=0.0)

    source_channel: Mapped[str] = mapped_column(String(32), default="email")  # email|pdf|scan|edi|portal
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    document_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(40), default=InvoiceStatus.RECEIVED, index=True)
    stage: Mapped[str] = mapped_column(String(40), default=WorkflowStage.INTAKE, index=True)
    match_result: Mapped[str] = mapped_column(String(40), default=MatchResult.NOT_RUN)
    match_details: Mapped[dict | None] = mapped_column(JSON, default=dict)

    extraction_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    extraction_fields: Mapped[dict | None] = mapped_column(JSON, default=dict)
    touchless: Mapped[bool] = mapped_column(Boolean, default=False)
    human_touches: Mapped[int] = mapped_column(Integer, default=0)

    duplicate_of_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duplicate_score: Mapped[float] = mapped_column(Float, default=0.0)

    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    sla_status: Mapped[str] = mapped_column(String(24), default=SLAStatus.ON_TRACK, index=True)
    sla_risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0)

    approver_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"), nullable=True)
    on_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    hold_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    erp_document_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    erp_posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    erp_system: Mapped[str] = mapped_column(String(32), default="SAP_S4HANA")

    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cycle_time_hours: Mapped[float | None] = mapped_column(Float, nullable=True)

    supplier = relationship("Supplier", back_populates="invoices")
    po = relationship("PurchaseOrder")
    lines = relationship("InvoiceLine", back_populates="invoice", cascade="all, delete-orphan")
    exceptions = relationship("ExceptionCase", back_populates="invoice", cascade="all, delete-orphan")
    approvals = relationship("Approval", back_populates="invoice", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_invoice_supplier_number", "supplier_id", "invoice_number"),)


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    invoice_id: Mapped[str] = mapped_column(String(32), ForeignKey("invoices.id"), index=True)
    line_number: Mapped[int] = mapped_column(Integer, default=1)
    item_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    uom: Mapped[str] = mapped_column(String(16), default="EA")
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)
    line_total: Mapped[float] = mapped_column(Float, default=0.0)
    tax_rate: Mapped[float] = mapped_column(Float, default=0.0)
    po_line_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    match_status: Mapped[str] = mapped_column(String(32), default="not_run")
    variance_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    invoice = relationship("Invoice", back_populates="lines")


class ExceptionCase(Base, TimestampMixin):
    __tablename__ = "exceptions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    case_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    invoice_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("invoices.id"), index=True)
    supplier_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("suppliers.id"), nullable=True)
    exception_type: Mapped[str] = mapped_column(String(48), index=True)
    severity: Mapped[str] = mapped_column(String(16), default=RiskLevel.MEDIUM)
    status: Mapped[str] = mapped_column(String(32), default=ExceptionStatus.OPEN, index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    detected_by: Mapped[str] = mapped_column(String(64), default="system")
    financial_impact_usd: Mapped[float] = mapped_column(Float, default=0.0)

    proposed_resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_by_agent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by_agent: Mapped[bool] = mapped_column(Boolean, default=False)

    assigned_to_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"), nullable=True)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    age_hours: Mapped[float] = mapped_column(Float, default=0.0)

    invoice = relationship("Invoice", back_populates="exceptions")


class Approval(Base, TimestampMixin):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    invoice_id: Mapped[str] = mapped_column(String(32), ForeignKey("invoices.id"), index=True)
    approver_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"), nullable=True)
    original_approver_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default=ApprovalStatus.PENDING, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reminders_sent: Mapped[int] = mapped_column(Integer, default=0)
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    routing_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    invoice = relationship("Invoice", back_populates="approvals")


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    payment_number: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    invoice_id: Mapped[str] = mapped_column(String(32), ForeignKey("invoices.id"), index=True)
    supplier_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("suppliers.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    discount_captured: Mapped[float] = mapped_column(Float, default=0.0)
    method: Mapped[str] = mapped_column(String(24), default="ACH")
    scheduled_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default=PaymentStatus.PROPOSED, index=True)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0)
    score_breakdown: Mapped[dict | None] = mapped_column(JSON, default=dict)
    released_by: Mapped[str | None] = mapped_column(String(160), nullable=True)

    invoice = relationship("Invoice")


class PurchaseRequest(Base, TimestampMixin):
    __tablename__ = "purchase_requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    request_number: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    requester_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"), nullable=True)
    requester_name: Mapped[str] = mapped_column(String(160), default="")
    supplier_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("suppliers.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    needed_by: Mapped[Date | None] = mapped_column(Date, nullable=True)
    cost_center: Mapped[str | None] = mapped_column(String(64), nullable=True)
    routing_decision: Mapped[str | None] = mapped_column(String(48), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="submitted", index=True)
    policy_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SupplierMessage(Base, TimestampMixin):
    __tablename__ = "supplier_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    thread_id: Mapped[str] = mapped_column(String(32), index=True, default=_uuid)
    supplier_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("suppliers.id"), nullable=True)
    invoice_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("invoices.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(24), default="portal")  # portal|email|teams|chat
    direction: Mapped[str] = mapped_column(String(16), default="inbound")  # inbound|outbound
    author: Mapped[str] = mapped_column(String(160), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    drafted_by_agent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    approved_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="received")  # received|draft|approved|sent


# ===========================================================================
# Agent control plane
# ===========================================================================
class AgentConfig(Base, TimestampMixin):
    """Per-agent governance settings, editable from the Agent Control Room."""

    __tablename__ = "agent_configs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    agent_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    autonomy_level: Mapped[str] = mapped_column(String(40), default=AutonomyLevel.HUMAN_APPROVAL)
    confidence_threshold: Mapped[float] = mapped_column(Float, default=0.90)
    max_auto_amount_usd: Mapped[float] = mapped_column(Float, default=5000.0)
    require_dual_approval_above_usd: Mapped[float] = mapped_column(Float, default=100000.0)
    allowed_actions: Mapped[list | None] = mapped_column(JSON, default=list)
    escalation_role: Mapped[str] = mapped_column(String(32), default=Role.AP_MANAGER)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    runs_total: Mapped[int] = mapped_column(Integer, default=0)
    proposals_total: Mapped[int] = mapped_column(Integer, default=0)
    approved_total: Mapped[int] = mapped_column(Integer, default=0)
    rejected_total: Mapped[int] = mapped_column(Integer, default=0)
    modified_total: Mapped[int] = mapped_column(Integer, default=0)


class AgentExecution(Base, TimestampMixin):
    """One agent run: the plan, the observations, the reasoning, the proposals."""

    __tablename__ = "agent_executions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    agent_key: Mapped[str] = mapped_column(String(64), index=True)
    agent_name: Mapped[str] = mapped_column(String(160), default="")
    trigger: Mapped[str] = mapped_column(String(64), default="manual")
    triggered_by: Mapped[str | None] = mapped_column(String(160), nullable=True)

    entity_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    entity_label: Mapped[str | None] = mapped_column(String(160), nullable=True)

    status: Mapped[str] = mapped_column(String(32), default=AgentRunStatus.QUEUED, index=True)
    goal: Mapped[str] = mapped_column(Text, default="")
    plan: Mapped[list | None] = mapped_column(JSON, default=list)          # [{step, tool, rationale}]
    observations: Mapped[list | None] = mapped_column(JSON, default=list)  # [{tool, input, output, ts}]
    reasoning: Mapped[str] = mapped_column(Text, default="")
    conclusion: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[list | None] = mapped_column(JSON, default=list)
    reasoning_engine: Mapped[str] = mapped_column(String(32), default="deterministic")
    policy_evaluation: Mapped[dict | None] = mapped_column(JSON, default=dict)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    parent_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    handoff_to: Mapped[str | None] = mapped_column(String(64), nullable=True)

    tasks = relationship("HumanTask", back_populates="execution", cascade="all, delete-orphan")


class HumanTask(Base, TimestampMixin):
    """A human-in-the-loop checkpoint.

    An agent NEVER mutates the system of record directly. It writes a HumanTask
    holding the proposed action + payload; the action executes only after a
    qualified human approves (or modifies and approves) it.
    """

    __tablename__ = "human_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    task_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    execution_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("agent_executions.id"), nullable=True, index=True
    )
    agent_key: Mapped[str] = mapped_column(String(64), index=True)
    agent_name: Mapped[str] = mapped_column(String(160), default="")

    stage: Mapped[str] = mapped_column(String(40), index=True)
    action_kind: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list | None] = mapped_column(JSON, default=list)
    proposed_payload: Mapped[dict | None] = mapped_column(JSON, default=dict)
    applied_payload: Mapped[dict | None] = mapped_column(JSON, default=dict)
    diff_preview: Mapped[list | None] = mapped_column(JSON, default=list)  # [{field, before, after}]
    alternatives: Mapped[list | None] = mapped_column(JSON, default=list)

    entity_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    entity_label: Mapped[str | None] = mapped_column(String(160), nullable=True)

    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(16), default=RiskLevel.MEDIUM)
    financial_impact_usd: Mapped[float] = mapped_column(Float, default=0.0)
    reversible: Mapped[bool] = mapped_column(Boolean, default=True)
    required_role: Mapped[str] = mapped_column(String(32), default=Role.AP_CLERK)
    assigned_to_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"), nullable=True)
    dual_approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    second_approver_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    second_approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    status: Mapped[str] = mapped_column(String(24), default=HumanTaskStatus.PENDING, index=True)
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    decided_by_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_result: Mapped[dict | None] = mapped_column(JSON, default=dict)
    execution_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    sla_status: Mapped[str] = mapped_column(String(24), default=SLAStatus.ON_TRACK)
    policy_flags: Mapped[list | None] = mapped_column(JSON, default=list)
    auto_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    execution = relationship("AgentExecution", back_populates="tasks")


class WorkflowEvent(Base):
    """Append-only stream powering the live activity feed and the invoice timeline."""

    __tablename__ = "workflow_events"

    # Integer PK so the stream has a strict, gap-free ordering on every backend.
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(32), unique=True, index=True, default=_uuid)
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    entity_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    actor: Mapped[str] = mapped_column(String(160), default="system")
    actor_type: Mapped[str] = mapped_column(String(24), default="system")  # agent|human|system
    title: Mapped[str] = mapped_column(String(255), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(16), default="info")
    payload: Mapped[dict | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AuditLog(Base):
    """Immutable audit trail. Every human decision and every applied action lands here."""

    __tablename__ = "audit_logs"

    # Integer PK so the hash chain has a strict, verifiable ordering.
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(32), unique=True, index=True, default=_uuid)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(160), default="system")
    actor_type: Mapped[str] = mapped_column(String(24), default="system")
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(96), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    entity_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    before_state: Mapped[dict | None] = mapped_column(JSON, default=dict)
    after_state: Mapped[dict | None] = mapped_column(JSON, default=dict)
    agent_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    human_task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    hitl_enforced: Mapped[bool] = mapped_column(Boolean, default=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash_chain: Mapped[str | None] = mapped_column(String(64), nullable=True)


class SLARisk(Base, TimestampMixin):
    __tablename__ = "sla_risks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    invoice_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("invoices.id"), index=True)
    entity_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    stage: Mapped[str] = mapped_column(String(40), default=WorkflowStage.INTAKE)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(16), default=RiskLevel.LOW)
    predicted_breach_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    hours_remaining: Mapped[float] = mapped_column(Float, default=0.0)
    drivers: Mapped[list | None] = mapped_column(JSON, default=list)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default=SLAStatus.ON_TRACK, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"), nullable=True)
    target_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(16), default="info")
    link_entity_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    link_entity_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class PolicyRule(Base, TimestampMixin):
    """Policy-as-code. Editable guardrails evaluated before any action executes."""

    __tablename__ = "policy_rules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(48), default="matching")
    description: Mapped[str] = mapped_column(Text, default="")
    value_type: Mapped[str] = mapped_column(String(24), default="number")  # number|percent|money|bool|text
    value: Mapped[str] = mapped_column(String(120), default="0")
    unit: Mapped[str | None] = mapped_column(String(24), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    editable: Mapped[bool] = mapped_column(Boolean, default=True)
    last_changed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)


# ===========================================================================
# Procurement AgentOps
# ===========================================================================
class Artifact(Base, TimestampMixin):
    """A file that flows into or out of an agent.

    One table for both directions, because the audit question is the same in
    each: which agent touched which document, when, and who released it.

    * ``direction="input"``  — an attachment a human uploaded for an agent to read.
    * ``direction="output"`` — a deliverable an agent produced. It is born as a
      DRAFT and only becomes ``released`` when a human approves the checkpoint
      that owns it, so a generated document cannot reach a supplier unreviewed.
    """

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    reference: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    direction: Mapped[str] = mapped_column(String(12), default="output", index=True)
    kind: Mapped[str] = mapped_column(String(48), default="document")
    title: Mapped[str] = mapped_column(String(255), default="")
    filename: Mapped[str] = mapped_column(String(255), default="")
    content_type: Mapped[str] = mapped_column(String(64), default="text/markdown")
    content: Mapped[str] = mapped_column(Text, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    agent_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    execution_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    human_task_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    released_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, default=dict)


class SourcingEvent(Base, TimestampMixin):
    __tablename__ = "sourcing_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    event_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    category: Mapped[str] = mapped_column(String(120), default="")
    event_type: Mapped[str] = mapped_column(String(16), default="RFP")  # RFP | RFQ | RFI
    budget_usd: Mapped[float] = mapped_column(Float, default=0.0)
    incumbent_spend_usd: Mapped[float] = mapped_column(Float, default=0.0)
    requirements: Mapped[str] = mapped_column(Text, default="")
    compliance_rules: Mapped[list | None] = mapped_column(JSON, default=list)
    weighting: Mapped[dict | None] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    owner_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"), nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    response_due: Mapped[Date | None] = mapped_column(Date, nullable=True)
    awarded_supplier_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    awarded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expected_savings_usd: Mapped[float] = mapped_column(Float, default=0.0)
    cycle_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_cycle_days: Mapped[float] = mapped_column(Float, default=56.0)

    bids = relationship("SourcingBid", back_populates="event", cascade="all, delete-orphan")


class SourcingBid(Base, TimestampMixin):
    __tablename__ = "sourcing_bids"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(String(32), ForeignKey("sourcing_events.id"), index=True)
    supplier_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("suppliers.id"), nullable=True)
    supplier_name: Mapped[str] = mapped_column(String(255), default="")
    bid_amount_usd: Mapped[float] = mapped_column(Float, default=0.0)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=0)
    technical_score: Mapped[float] = mapped_column(Float, default=0.0)
    commercial_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    total_score: Mapped[float] = mapped_column(Float, default=0.0)
    compliance_flags: Mapped[list | None] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="received")

    event = relationship("SourcingEvent", back_populates="bids")


class SpendTransaction(Base):
    __tablename__ = "spend_transactions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    supplier_raw: Mapped[str] = mapped_column(String(255), default="")
    supplier_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("suppliers.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    amount_usd: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    transaction_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    cost_center: Mapped[str | None] = mapped_column(String(64), nullable=True)
    po_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    on_contract: Mapped[bool] = mapped_column(Boolean, default=False)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    unspsc: Mapped[str | None] = mapped_column(String(16), nullable=True)
    classification_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    classified_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    maverick: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    tail_spend: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    source_artifact_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SavingsOpportunity(Base, TimestampMixin):
    __tablename__ = "savings_opportunities"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    reference: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    lever: Mapped[str] = mapped_column(String(64), default="consolidation", index=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    supplier_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    annual_spend_usd: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_savings_usd: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    rationale: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="identified", index=True)
    identified_by_agent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(160), nullable=True)


class RiskAssessment(Base, TimestampMixin):
    """A point-in-time strategic supplier risk scorecard across four domains."""

    __tablename__ = "risk_assessments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    supplier_id: Mapped[str] = mapped_column(String(32), ForeignKey("suppliers.id"), index=True)
    supplier_name: Mapped[str] = mapped_column(String(255), default="")
    financial_risk: Mapped[float] = mapped_column(Float, default=0.0)
    operational_risk: Mapped[float] = mapped_column(Float, default=0.0)
    compliance_risk: Mapped[float] = mapped_column(Float, default=0.0)
    esg_risk: Mapped[float] = mapped_column(Float, default=0.0)
    overall_risk: Mapped[float] = mapped_column(Float, default=0.0)
    risk_band: Mapped[str] = mapped_column(String(16), default="low", index=True)
    findings: Mapped[list | None] = mapped_column(JSON, default=list)
    recommended_disposition: Mapped[str] = mapped_column(String(24), default="approve")
    applied_disposition: Mapped[str | None] = mapped_column(String(24), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    spend_at_risk_usd: Mapped[float] = mapped_column(Float, default=0.0)


class ContractDraft(Base, TimestampMixin):
    __tablename__ = "contract_drafts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    reference: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    contract_type: Mapped[str] = mapped_column(String(24), default="MSA")  # MSA|SOW|NDA|Amendment
    supplier_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("suppliers.id"), nullable=True)
    supplier_name: Mapped[str] = mapped_column(String(255), default="")
    value_usd: Mapped[float] = mapped_column(Float, default=0.0)
    term_months: Mapped[int] = mapped_column(Integer, default=12)
    body: Mapped[str] = mapped_column(Text, default="")
    clause_findings: Mapped[list | None] = mapped_column(JSON, default=list)
    missing_clauses: Mapped[list | None] = mapped_column(JSON, default=list)
    legal_risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    obligations: Mapped[list | None] = mapped_column(JSON, default=list)
    renewal_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="drafted", index=True)
    issued_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_artifact_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


class TailSpendFinding(Base, TimestampMixin):
    __tablename__ = "tail_spend_findings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    reference: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    finding_type: Mapped[str] = mapped_column(String(48), default="off_contract", index=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    supplier_names: Mapped[list | None] = mapped_column(JSON, default=list)
    transaction_count: Mapped[int] = mapped_column(Integer, default=0)
    spend_usd: Mapped[float] = mapped_column(Float, default=0.0)
    recommended_supplier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    consolidation_savings_usd: Mapped[float] = mapped_column(Float, default=0.0)
    recommendation: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    resolved_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
