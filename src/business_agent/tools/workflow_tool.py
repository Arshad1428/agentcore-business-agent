from __future__ import annotations

from strands import tool


@tool
def run_workflow(workflow: str, product: str = "", quantity: int = 0, department: str = "",
                 approval_id: str = "", order_id: str = "") -> dict:
    """Run a configured business workflow end to end and return its step report.

    Workflows: "purchase_order" (needs product, quantity, department; optional
    approval_id to resume after manager approval) and "order_status_check" (needs
    order_id). It validates, quotes, requests approval when required, creates the
    simulated order and notifies the department. If status is "pending_approval",
    tell the user the approval_id and that a manager must approve it first.

    Args:
        workflow: Workflow name.
        product: Catalog product name (purchase_order).
        quantity: Whole number of units (purchase_order).
        department: Department name (purchase_order).
        approval_id: Approved request id, to resume a paused purchase_order.
        order_id: Order id (order_status_check).

    Returns:
        {"workflow", "status": "completed"|"failed"|"pending_approval", "failed_step", "steps"}
        or {"ok": False, "error"} for an unknown workflow or missing inputs.
    """
    from business_agent.workflows import WorkflowError, run_workflow as _run

    candidates = {"product": product, "quantity": quantity or None, "department": department,
                  "approval_id": approval_id, "order_id": order_id}
    inputs = {k: v for k, v in candidates.items() if v not in (None, "")}
    if workflow == "purchase_order":
        inputs.pop("order_id", None)
    elif workflow == "order_status_check":
        inputs = {k: v for k, v in inputs.items() if k == "order_id"}
    try:
        return _run(workflow, inputs)
    except WorkflowError as exc:
        return {"ok": False, "error": str(exc)}
