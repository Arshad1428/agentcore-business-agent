from __future__ import annotations

import uuid

from strands import tool

from business_agent.data.products import APPROVAL_THRESHOLD, CURRENCY, find_department

# Simulated approval store (in-memory, per process).
_APPROVALS: dict[str, dict] = {}


def clear_approvals() -> None:
    _APPROVALS.clear()


def grant_approval(approval_id: str) -> dict:
    """Manager action (NOT an agent tool): approve a pending request.

    Exposed only through the Runtime {"action": "approve"} so the model can never
    approve its own requests.
    """
    rec = _APPROVALS.get(approval_id)
    if rec is None:
        return {"ok": False, "error": f"Unknown approval_id '{approval_id}'."}
    rec["status"] = "approved"
    return {"ok": True, "approval_id": approval_id, "status": "approved"}


def is_approved(approval_id: str, amount: float, department: str) -> bool:
    rec = _APPROVALS.get(approval_id or "")
    return bool(
        rec
        and rec["status"] == "approved"
        and rec["department"] == department
        and amount <= rec["amount"]
    )


@tool
def request_approval(amount: float, department: str, approval_id: str = "") -> dict:
    """Check whether an order total needs manager approval, and request it if so.

    Orders at or below the threshold are auto-approved. Above it, a pending
    approval request is created and the order must NOT be placed until a manager
    approves it. To re-check a request later, pass the approval_id you were given.

    Args:
        amount: Order total from calculate_order_total.
        department: One of Engineering, Finance, HR, Marketing, Operations.
        approval_id: Optional id of an earlier approval request to re-check.

    Returns:
        {"ok": True, "approved": bool, "approval_id", "status"} or {"ok": False, "error"}.
        status is "auto_approved", "approved" or "pending_manager_approval".
    """
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount < 0:
        return {"ok": False, "error": "amount must be a non-negative number."}
    dept = find_department(department)
    if dept is None:
        return {"ok": False, "error": "Unknown department."}

    if amount <= APPROVAL_THRESHOLD:
        return {"ok": True, "approved": True, "approval_id": None, "status": "auto_approved"}

    if approval_id:
        rec = _APPROVALS.get(approval_id)
        if rec is None:
            return {"ok": False, "error": f"Unknown approval_id '{approval_id}'."}
        approved = is_approved(approval_id, amount, dept)
        return {
            "ok": True,
            "approved": approved,
            "approval_id": approval_id,
            "status": "approved" if approved else "pending_manager_approval",
        }

    new_id = f"APR-{uuid.uuid4().hex[:8].upper()}"
    _APPROVALS[new_id] = {"amount": amount, "department": dept, "status": "pending"}
    return {
        "ok": True,
        "approved": False,
        "approval_id": new_id,
        "status": "pending_manager_approval",
        "message": f"Total {amount} {CURRENCY} exceeds {APPROVAL_THRESHOLD}; manager approval required.",
    }
