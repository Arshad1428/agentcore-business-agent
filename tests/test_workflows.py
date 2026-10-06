"""Deterministic workflow-engine, approval and notification tests. No LLM, no AWS."""
import pytest

from business_agent.tools import WORKFLOW_TOOLS, create_order, request_approval
from business_agent.tools.approval import clear_approvals, grant_approval
from business_agent.tools.notification import clear_outbox, get_outbox
from business_agent.tools.order import clear_orders, get_order_status, get_orders
from business_agent.workflows import WorkflowError, list_workflows, run_workflow


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("SIMULATE_TOOL_FAILURE", raising=False)
    clear_orders(); clear_approvals(); clear_outbox()


PO = {"product": "monitor", "quantity": 3, "department": "Engineering"}


def statuses(report):
    return [(s["id"], s["status"]) for s in report["steps"]]


def test_list_workflows():
    names = [w["name"] for w in list_workflows()]
    assert "purchase_order" in names and "order_status_check" in names


def test_purchase_order_happy_path():
    r = run_workflow("purchase_order", PO)
    assert r["status"] == "completed" and r["failed_step"] is None
    assert all(s == "success" for _, s in statuses(r))
    assert len(get_orders()) == 1 and get_orders()[0]["total"] == 45000
    assert get_outbox()[0]["reference"] == get_orders()[0]["order_id"]


def test_failure_stops_workflow_and_skips_rest():
    r = run_workflow("purchase_order", {**PO, "product": "quantum keyboard"})
    assert r["status"] == "failed" and r["failed_step"] == "lookup"
    assert statuses(r)[1:] == [("quote", "skipped"), ("approval", "skipped"),
                               ("create", "skipped"), ("notify", "skipped")]
    assert get_orders() == [] and get_outbox() == []


def test_out_of_stock_fails_at_create_without_notification():
    r = run_workflow("purchase_order", {**PO, "product": "mouse"})
    assert r["status"] == "failed" and r["failed_step"] == "create"
    assert get_orders() == [] and get_outbox() == []


def test_tool_exception_is_contained(monkeypatch):
    monkeypatch.setenv("SIMULATE_TOOL_FAILURE", "1")
    r = run_workflow("purchase_order", PO)
    assert r["status"] == "failed" and r["failed_step"] == "create"
    assert "Traceback" not in str(r) and get_orders() == []


def test_high_value_order_pauses_for_approval_then_resumes():
    big = {"product": "laptop", "quantity": 2, "department": "Finance"}  # 170000 > threshold
    first = run_workflow("purchase_order", big)
    assert first["status"] == "pending_approval" and get_orders() == []
    aid = first["steps"][2]["output"]["approval_id"]

    still = run_workflow("purchase_order", {**big, "approval_id": aid})
    assert still["status"] == "pending_approval" and get_orders() == []  # not approved yet

    assert grant_approval(aid)["ok"]
    done = run_workflow("purchase_order", {**big, "approval_id": aid})
    assert done["status"] == "completed" and len(get_orders()) == 1


def test_create_order_enforces_approval_even_without_workflow():
    r = create_order("laptop", 2, "Finance")
    assert r["ok"] is False and "approval" in r["error"] and get_orders() == []


def test_approval_cannot_be_reused_for_other_department():
    aid = request_approval(170000, "Finance")["approval_id"]
    grant_approval(aid)
    assert create_order("laptop", 2, "HR", approval_id=aid)["ok"] is False
    assert create_order("laptop", 2, "Finance", approval_id=aid)["ok"] is True


def test_request_approval_validation():
    assert request_approval(100, "Narnia")["ok"] is False
    assert request_approval(-1, "HR")["ok"] is False
    assert request_approval(100, "HR")["status"] == "auto_approved"
    assert request_approval(170000, "HR", approval_id="APR-NOPE")["ok"] is False


def test_order_status_check_workflow():
    run_workflow("purchase_order", PO)
    oid = get_orders()[0]["order_id"]
    assert get_order_status(oid)["status"] == "created"
    r = run_workflow("order_status_check", {"order_id": oid})
    assert r["status"] == "completed"
    assert run_workflow("order_status_check", {"order_id": "ORD-NOPE"})["status"] == "failed"


@pytest.mark.parametrize(
    "name,inputs",
    [
        ("nope", {}),
        ("purchase_order", {}),
        ("purchase_order", {"product": "monitor"}),
        ("purchase_order", {**PO, "extra": 1}),
        ("purchase_order", "text"),
    ],
)
def test_invalid_workflow_requests_raise(name, inputs):
    with pytest.raises(WorkflowError):
        run_workflow(name, inputs)


def test_workflow_references_only_registered_tools():
    from business_agent.workflows import WORKFLOWS

    for wf in WORKFLOWS.values():
        for step in wf["steps"]:
            assert step["tool"] in WORKFLOW_TOOLS
