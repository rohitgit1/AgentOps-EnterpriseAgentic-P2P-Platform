"""Approval routing skill — pick the right approver, honouring limits, OOO and load."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..enums import ROLE_AUTHORITY, Role
from ..models import User, utcnow

SKILL = {
    "name": "approval_routing",
    "title": "Approval Routing",
    "purpose": "Select an approver with sufficient authority who is available and not overloaded.",
    "inputs": ["invoice_amount", "cost_center", "requester", "delegation_matrix", "calendar"],
    "output": ["approver", "level", "reason", "alternates"],
    "success_criteria": "No invoice routed to an approver who is out of office or under-authorised.",
    "failure_handling": "If nobody qualifies, escalate to Controller with a documented reason.",
    "used_by": ["approval_acceleration", "sla_command_center"],
}


def _available(user: User) -> bool:
    if not user.is_active:
        return False
    if user.out_of_office:
        if user.ooo_until is None or user.ooo_until > utcnow():
            return False
    return True


def route(
    db: Session,
    *,
    amount_usd: float,
    exclude_ids: list[str] | None = None,
    minimum_role: str = Role.AP_MANAGER,
) -> dict:
    exclude = set(exclude_ids or [])
    users = db.execute(select(User).where(User.is_active.is_(True))).scalars().all()

    qualified = [
        u
        for u in users
        if u.id not in exclude
        and u.approval_limit_usd >= amount_usd
        and ROLE_AUTHORITY.get(u.role, 0) >= ROLE_AUTHORITY.get(str(minimum_role), 0)
    ]

    reasons: list[str] = []
    rerouted_from: dict | None = None

    available = [u for u in qualified if _available(u)]
    if not available and qualified:
        # Everyone qualified is out — follow the delegation matrix.
        for absentee in qualified:
            delegate = db.get(User, absentee.delegate_id) if absentee.delegate_id else None
            if delegate and _available(delegate) and delegate.approval_limit_usd >= amount_usd:
                rerouted_from = {"id": absentee.id, "name": absentee.full_name}
                reasons.append(
                    f"{absentee.full_name} is out of office; routed to delegate {delegate.full_name}."
                )
                available = [delegate]
                break

    if not available:
        controller = next(
            (u for u in users if u.role in {Role.CONTROLLER, Role.CFO} and _available(u)), None
        )
        if controller is None:
            return {
                "approver": None,
                "reason": "No approver with sufficient authority is available.",
                "alternates": [],
                "requires_human_review": True,
            }
        reasons.append("No standard approver available — escalated to Controller.")
        available = [controller]

    # Prefer the lowest-authority qualified approver with the lightest queue:
    # authority is spent where it is needed, not by default.
    available.sort(key=lambda u: (ROLE_AUTHORITY.get(u.role, 0), u.active_workload or 0))
    chosen = available[0]
    level = 2 if amount_usd >= 50_000 else 1
    reasons.append(
        f"{chosen.full_name} ({chosen.title or chosen.role}) holds a "
        f"${chosen.approval_limit_usd:,.0f} limit against a ${amount_usd:,.2f} invoice."
    )
    reasons.append(f"Current queue depth: {chosen.active_workload or 0} open approvals.")

    return {
        "approver": {
            "id": chosen.id,
            "name": chosen.full_name,
            "role": chosen.role,
            "title": chosen.title,
            "approval_limit_usd": chosen.approval_limit_usd,
            "workload": chosen.active_workload or 0,
        },
        "level": level,
        "rerouted_from": rerouted_from,
        "reason": " ".join(reasons),
        "alternates": [
            {"id": u.id, "name": u.full_name, "role": u.role, "workload": u.active_workload or 0}
            for u in available[1:4]
        ],
        "requires_human_review": False,
    }
