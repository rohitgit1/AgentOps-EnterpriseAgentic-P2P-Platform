"""Domain vocabulary for the P2P lifecycle and the agent control plane."""
from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class AgentSuite(StrEnum):
    """The platform ships two agent suites over one control plane."""

    P2P = "p2p"                    # operational Procure-to-Pay
    PROCUREMENT = "procurement"    # strategic sourcing & category management


SUITE_LABELS: dict[str, str] = {
    AgentSuite.P2P: "P2P AgentOps",
    AgentSuite.PROCUREMENT: "Procurement AgentOps",
}

SUITE_BLURBS: dict[str, str] = {
    AgentSuite.P2P: "Operational accounts payable — intake to payment.",
    AgentSuite.PROCUREMENT: "Strategic sourcing, spend, supplier risk, contracts and tail spend.",
}


# --------------------------------------------------------------------------
# People & governance
# --------------------------------------------------------------------------
class Role(StrEnum):
    AP_CLERK = "ap_clerk"
    AP_MANAGER = "ap_manager"
    CONTROLLER = "controller"
    PROCUREMENT = "procurement"
    TREASURY = "treasury"
    CFO = "cfo"
    SUPPLIER = "supplier"
    ADMIN = "admin"


ROLE_LABELS: dict[str, str] = {
    Role.AP_CLERK: "AP Clerk",
    Role.AP_MANAGER: "AP Manager",
    Role.CONTROLLER: "Controller",
    Role.PROCUREMENT: "Procurement Lead",
    Role.TREASURY: "Treasury Analyst",
    Role.CFO: "CFO",
    Role.SUPPLIER: "Supplier",
    Role.ADMIN: "Platform Admin",
}

# Ordered least -> most authority. Used for "can this human decide this task?"
ROLE_AUTHORITY: dict[str, int] = {
    Role.SUPPLIER: 0,
    Role.AP_CLERK: 10,
    Role.PROCUREMENT: 20,
    Role.TREASURY: 20,
    Role.AP_MANAGER: 30,
    Role.CONTROLLER: 40,
    Role.CFO: 50,
    Role.ADMIN: 60,
}


class AutonomyLevel(StrEnum):
    """How much rope a given agent is given. Enforced by the policy engine."""

    OBSERVE_ONLY = "observe_only"          # L0 - analyse, never propose
    SUGGEST = "suggest"                    # L1 - propose, human must act
    HUMAN_APPROVAL = "human_approval"      # L2 - propose + stage change, human approves (DEFAULT)
    AUTO_WITHIN_GUARDRAILS = "auto_within_guardrails"  # L3 - auto-execute only inside policy envelope
    FULL_AUTO = "full_auto"                # L4 - disabled while global HITL enforcement is on


AUTONOMY_LABELS: dict[str, str] = {
    AutonomyLevel.OBSERVE_ONLY: "L0 · Observe Only",
    AutonomyLevel.SUGGEST: "L1 · Suggest",
    AutonomyLevel.HUMAN_APPROVAL: "L2 · Human Approval",
    AutonomyLevel.AUTO_WITHIN_GUARDRAILS: "L3 · Auto within Guardrails",
    AutonomyLevel.FULL_AUTO: "L4 · Full Auto",
}


# --------------------------------------------------------------------------
# Workflow
# --------------------------------------------------------------------------
class WorkflowStage(StrEnum):
    INTAKE = "intake"
    EXTRACTION_REVIEW = "extraction_review"
    VALIDATION = "validation"
    MATCHING = "matching"
    EXCEPTION = "exception"
    APPROVAL = "approval"
    PAYMENT = "payment"
    POSTED = "posted"
    CLOSED = "closed"
    REJECTED = "rejected"


STAGE_SEQUENCE: list[str] = [
    WorkflowStage.INTAKE,
    WorkflowStage.EXTRACTION_REVIEW,
    WorkflowStage.VALIDATION,
    WorkflowStage.MATCHING,
    WorkflowStage.EXCEPTION,
    WorkflowStage.APPROVAL,
    WorkflowStage.PAYMENT,
    WorkflowStage.POSTED,
    WorkflowStage.CLOSED,
]

STAGE_LABELS: dict[str, str] = {
    WorkflowStage.INTAKE: "Intake",
    WorkflowStage.EXTRACTION_REVIEW: "Extraction Review",
    WorkflowStage.VALIDATION: "Validation",
    WorkflowStage.MATCHING: "3-Way Match",
    WorkflowStage.EXCEPTION: "Exception Resolution",
    WorkflowStage.APPROVAL: "Approval",
    WorkflowStage.PAYMENT: "Payment Readiness",
    WorkflowStage.POSTED: "Posted to ERP",
    WorkflowStage.CLOSED: "Closed",
    WorkflowStage.REJECTED: "Rejected",
}


class InvoiceStatus(StrEnum):
    RECEIVED = "received"
    EXTRACTING = "extracting"
    PENDING_REVIEW = "pending_review"
    VALIDATED = "validated"
    MATCHED = "matched"
    ON_HOLD = "on_hold"
    IN_EXCEPTION = "in_exception"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SCHEDULED_FOR_PAYMENT = "scheduled_for_payment"
    PAID = "paid"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class MatchResult(StrEnum):
    NOT_RUN = "not_run"
    MATCHED = "matched"
    WITHIN_TOLERANCE = "within_tolerance"
    PRICE_VARIANCE = "price_variance"
    QUANTITY_VARIANCE = "quantity_variance"
    MISSING_RECEIPT = "missing_receipt"
    MISSING_PO = "missing_po"
    NO_MATCH = "no_match"


class ExceptionType(StrEnum):
    MISSING_RECEIPT = "missing_receipt"
    PRICE_MISMATCH = "price_mismatch"
    QUANTITY_MISMATCH = "quantity_mismatch"
    DUPLICATE_INVOICE = "duplicate_invoice"
    TAX_ERROR = "tax_error"
    SUPPLIER_DISPUTE = "supplier_dispute"
    MISSING_PO = "missing_po"
    CONTRACT_RATE_BREACH = "contract_rate_breach"
    BANKING_CHANGE = "banking_change"
    SANCTIONS_HIT = "sanctions_hit"
    LOW_CONFIDENCE_EXTRACTION = "low_confidence_extraction"


class ExceptionStatus(StrEnum):
    OPEN = "open"
    AGENT_PROPOSED = "agent_proposed"
    AWAITING_SUPPLIER = "awaiting_supplier"
    AWAITING_HUMAN = "awaiting_human"
    RESOLVED = "resolved"
    WRITTEN_OFF = "written_off"
    ESCALATED = "escalated"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DELEGATED = "delegated"
    ESCALATED = "escalated"
    EXPIRED = "expired"


class PaymentStatus(StrEnum):
    NOT_SCHEDULED = "not_scheduled"
    PROPOSED = "proposed"
    SCHEDULED = "scheduled"
    RELEASED = "released"
    PAID = "paid"
    FAILED = "failed"
    ON_HOLD = "on_hold"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SLAStatus(StrEnum):
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    BREACHED = "breached"
    MET = "met"


# --------------------------------------------------------------------------
# Human-in-the-loop control plane
# --------------------------------------------------------------------------
class HumanTaskStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"          # human edited the payload, then approved
    INFO_REQUESTED = "info_requested"
    ESCALATED = "escalated"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"        # agent recalled the proposal


class HumanDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    MODIFY_AND_APPROVE = "modify_and_approve"
    REQUEST_INFO = "request_info"
    ESCALATE = "escalate"


class AgentRunStatus(StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    EXECUTING = "executing"
    AWAITING_HUMAN = "awaiting_human"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED_BY_POLICY = "blocked_by_policy"
    CANCELLED = "cancelled"


class ActionKind(StrEnum):
    """Every state-changing thing an agent can propose. Nothing else is executable."""

    UPDATE_INVOICE_FIELDS = "update_invoice_fields"
    ADVANCE_STAGE = "advance_stage"
    POST_TO_ERP = "post_to_erp"
    CREATE_EXCEPTION = "create_exception"
    RESOLVE_EXCEPTION = "resolve_exception"
    HOLD_INVOICE = "hold_invoice"
    RELEASE_HOLD = "release_hold"
    ROUTE_FOR_APPROVAL = "route_for_approval"
    SEND_APPROVAL_REMINDER = "send_approval_reminder"
    ESCALATE_APPROVAL = "escalate_approval"
    REASSIGN_APPROVER = "reassign_approver"
    SEND_SUPPLIER_MESSAGE = "send_supplier_message"
    REQUEST_GOODS_RECEIPT = "request_goods_receipt"
    SCHEDULE_PAYMENT = "schedule_payment"
    RELEASE_PAYMENT = "release_payment"
    BLOCK_SUPPLIER = "block_supplier"
    UPDATE_SUPPLIER_MASTER = "update_supplier_master"
    FLAG_CONTRACT_BREACH = "flag_contract_breach"
    CREATE_PURCHASE_REQUEST = "create_purchase_request"
    APPROVE_PURCHASE_REQUEST = "approve_purchase_request"
    REBALANCE_WORKLOAD = "rebalance_workload"
    RAISE_EXECUTIVE_ALERT = "raise_executive_alert"

    # --- Procurement AgentOps -------------------------------------------
    ISSUE_RFP = "issue_rfp"
    AWARD_SOURCING_EVENT = "award_sourcing_event"
    PUBLISH_SPEND_CLASSIFICATION = "publish_spend_classification"
    CREATE_SAVINGS_OPPORTUNITY = "create_savings_opportunity"
    SET_SUPPLIER_DISPOSITION = "set_supplier_disposition"
    DRAFT_CONTRACT = "draft_contract"
    ISSUE_CONTRACT_FOR_SIGNATURE = "issue_contract_for_signature"
    CONSOLIDATE_SUPPLIERS = "consolidate_suppliers"
    ENFORCE_CATALOG = "enforce_catalog"
    PUBLISH_EXECUTIVE_BRIEF = "publish_executive_brief"

    NO_OP = "no_op"


# Irreversible / money-moving / outward-facing actions.
# These ALWAYS require a human decision, even at L3 autonomy.
IRREVERSIBLE_ACTIONS: set[str] = {
    ActionKind.POST_TO_ERP,
    ActionKind.RELEASE_PAYMENT,
    ActionKind.SEND_SUPPLIER_MESSAGE,
    ActionKind.UPDATE_SUPPLIER_MASTER,
    ActionKind.BLOCK_SUPPLIER,
    ActionKind.APPROVE_PURCHASE_REQUEST,
    ActionKind.SCHEDULE_PAYMENT,
    # Procurement: each of these reaches a supplier or commits the company.
    ActionKind.ISSUE_RFP,
    ActionKind.AWARD_SOURCING_EVENT,
    ActionKind.ISSUE_CONTRACT_FOR_SIGNATURE,
    ActionKind.CONSOLIDATE_SUPPLIERS,
    ActionKind.PUBLISH_EXECUTIVE_BRIEF,
}

# Minimum role authority required to decide an action.
ACTION_MIN_ROLE: dict[str, str] = {
    ActionKind.UPDATE_INVOICE_FIELDS: Role.AP_CLERK,
    ActionKind.ADVANCE_STAGE: Role.AP_CLERK,
    ActionKind.CREATE_EXCEPTION: Role.AP_CLERK,
    ActionKind.RESOLVE_EXCEPTION: Role.AP_CLERK,
    ActionKind.HOLD_INVOICE: Role.AP_CLERK,
    ActionKind.RELEASE_HOLD: Role.AP_MANAGER,
    ActionKind.ROUTE_FOR_APPROVAL: Role.AP_CLERK,
    ActionKind.SEND_APPROVAL_REMINDER: Role.AP_CLERK,
    ActionKind.ESCALATE_APPROVAL: Role.AP_MANAGER,
    ActionKind.REASSIGN_APPROVER: Role.AP_MANAGER,
    ActionKind.SEND_SUPPLIER_MESSAGE: Role.AP_CLERK,
    ActionKind.REQUEST_GOODS_RECEIPT: Role.AP_CLERK,
    ActionKind.POST_TO_ERP: Role.AP_MANAGER,
    ActionKind.SCHEDULE_PAYMENT: Role.TREASURY,
    ActionKind.RELEASE_PAYMENT: Role.CONTROLLER,
    ActionKind.BLOCK_SUPPLIER: Role.CONTROLLER,
    ActionKind.UPDATE_SUPPLIER_MASTER: Role.CONTROLLER,
    ActionKind.FLAG_CONTRACT_BREACH: Role.PROCUREMENT,
    ActionKind.CREATE_PURCHASE_REQUEST: Role.AP_CLERK,
    ActionKind.APPROVE_PURCHASE_REQUEST: Role.PROCUREMENT,
    ActionKind.REBALANCE_WORKLOAD: Role.AP_MANAGER,
    ActionKind.RAISE_EXECUTIVE_ALERT: Role.AP_MANAGER,
    ActionKind.NO_OP: Role.AP_CLERK,
    # --- Procurement AgentOps -------------------------------------------
    ActionKind.ISSUE_RFP: Role.PROCUREMENT,
    ActionKind.AWARD_SOURCING_EVENT: Role.PROCUREMENT,
    ActionKind.PUBLISH_SPEND_CLASSIFICATION: Role.PROCUREMENT,
    ActionKind.CREATE_SAVINGS_OPPORTUNITY: Role.PROCUREMENT,
    ActionKind.SET_SUPPLIER_DISPOSITION: Role.PROCUREMENT,
    ActionKind.DRAFT_CONTRACT: Role.PROCUREMENT,
    ActionKind.ISSUE_CONTRACT_FOR_SIGNATURE: Role.CONTROLLER,
    ActionKind.CONSOLIDATE_SUPPLIERS: Role.PROCUREMENT,
    ActionKind.ENFORCE_CATALOG: Role.PROCUREMENT,
    ActionKind.PUBLISH_EXECUTIVE_BRIEF: Role.CFO,
}

ACTION_LABELS: dict[str, str] = {
    ActionKind.UPDATE_INVOICE_FIELDS: "Correct invoice fields",
    ActionKind.ADVANCE_STAGE: "Advance workflow stage",
    ActionKind.POST_TO_ERP: "Post to ERP",
    ActionKind.CREATE_EXCEPTION: "Open exception",
    ActionKind.RESOLVE_EXCEPTION: "Resolve exception",
    ActionKind.HOLD_INVOICE: "Place invoice on hold",
    ActionKind.RELEASE_HOLD: "Release hold",
    ActionKind.ROUTE_FOR_APPROVAL: "Route for approval",
    ActionKind.SEND_APPROVAL_REMINDER: "Send approval reminder",
    ActionKind.ESCALATE_APPROVAL: "Escalate approval",
    ActionKind.REASSIGN_APPROVER: "Reroute to delegate",
    ActionKind.SEND_SUPPLIER_MESSAGE: "Send supplier message",
    ActionKind.REQUEST_GOODS_RECEIPT: "Request goods receipt",
    ActionKind.SCHEDULE_PAYMENT: "Schedule payment",
    ActionKind.RELEASE_PAYMENT: "Release payment",
    ActionKind.BLOCK_SUPPLIER: "Block supplier",
    ActionKind.UPDATE_SUPPLIER_MASTER: "Update supplier master",
    ActionKind.FLAG_CONTRACT_BREACH: "Flag contract breach",
    ActionKind.CREATE_PURCHASE_REQUEST: "Create purchase request",
    ActionKind.APPROVE_PURCHASE_REQUEST: "Approve purchase request",
    ActionKind.REBALANCE_WORKLOAD: "Rebalance workload",
    ActionKind.RAISE_EXECUTIVE_ALERT: "Raise executive alert",
    ActionKind.NO_OP: "No action required",
    # --- Procurement AgentOps -------------------------------------------
    ActionKind.ISSUE_RFP: "Issue RFP to suppliers",
    ActionKind.AWARD_SOURCING_EVENT: "Award sourcing event",
    ActionKind.PUBLISH_SPEND_CLASSIFICATION: "Publish spend classification",
    ActionKind.CREATE_SAVINGS_OPPORTUNITY: "Log savings opportunity",
    ActionKind.SET_SUPPLIER_DISPOSITION: "Set supplier disposition",
    ActionKind.DRAFT_CONTRACT: "Save contract draft",
    ActionKind.ISSUE_CONTRACT_FOR_SIGNATURE: "Issue contract for signature",
    ActionKind.CONSOLIDATE_SUPPLIERS: "Consolidate suppliers",
    ActionKind.ENFORCE_CATALOG: "Enforce catalog buying",
    ActionKind.PUBLISH_EXECUTIVE_BRIEF: "Publish executive brief",
}


class EventType(StrEnum):
    INVOICE_RECEIVED = "invoice.received"
    INVOICE_UPDATED = "invoice.updated"
    STAGE_CHANGED = "invoice.stage_changed"
    AGENT_STARTED = "agent.started"
    AGENT_STEP = "agent.step"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    AGENT_BLOCKED = "agent.blocked"
    HUMAN_TASK_CREATED = "hitl.task_created"
    HUMAN_TASK_DECIDED = "hitl.task_decided"
    EXCEPTION_OPENED = "exception.opened"
    EXCEPTION_RESOLVED = "exception.resolved"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_DECIDED = "approval.decided"
    PAYMENT_SCHEDULED = "payment.scheduled"
    PAYMENT_RELEASED = "payment.released"
    SLA_AT_RISK = "sla.at_risk"
    SLA_BREACHED = "sla.breached"
    SUPPLIER_MESSAGE = "supplier.message"
    RISK_ALERT = "risk.alert"
    POLICY_BLOCK = "policy.block"
    SYSTEM = "system"
    # --- Procurement AgentOps (matches the spec's communication framework)
    SOURCING_EVENT_CREATED = "sourcing.event_created"
    SOURCING_EVENT_AWARDED = "sourcing.event_awarded"
    SAVING_OPPORTUNITY_DETECTED = "spend.saving_opportunity_detected"
    SUPPLIER_RISK_ALERT = "supplier.risk_alert"
    CONTRACT_EXPIRING = "contract.expiring"
    CONTRACT_DRAFTED = "contract.drafted"
    MAVERICK_SPEND_DETECTED = "tailspend.maverick_detected"
    ARTIFACT_PRODUCED = "artifact.produced"
    ARTIFACT_RELEASED = "artifact.released"
