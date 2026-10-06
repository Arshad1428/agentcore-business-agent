"""Runtime wrapper tests using a fake agent. No LLM, no AWS, no cost."""
import pytest

pytest.importorskip("bedrock_agentcore")

from business_agent import runtime  # noqa: E402
from business_agent.agent import extract_tool_calls  # noqa: E402


def _history():
    return [
        {"role": "user", "content": [{"text": "hi"}]},
        {"role": "assistant", "content": [{"toolUse": {"toolUseId": "1", "name": "lookup_product", "input": {"product_name": "monitor"}}}]},
        {"role": "user", "content": [{"toolResult": {"toolUseId": "1", "status": "success", "content": [{"json": {"ok": True}}]}}]},
        {"role": "assistant", "content": [{"toolUse": {"toolUseId": "2", "name": "create_order", "input": {}}}]},
        {"role": "user", "content": [{"toolResult": {"toolUseId": "2", "status": "error", "content": [{"text": "boom"}]}}]},
        {"role": "assistant", "content": [{"toolUse": {"toolUseId": "3", "name": "lookup_product", "input": {}}}]},
        {"role": "user", "content": [{"toolResult": {"toolUseId": "3", "status": "success", "content": [{"json": {"ok": False, "error": "x"}}]}}]},
    ]


def test_extract_tool_calls_statuses():
    calls = extract_tool_calls(_history())
    assert [(c["name"], c["status"]) for c in calls] == [
        ("lookup_product", "success"),
        ("create_order", "error"),
        ("lookup_product", "error"),  # ok=false payload counts as a failure
    ]


class FakeAgent:
    def __init__(self, fail=False):
        self.messages, self.fail = [], fail

    def __call__(self, prompt):
        if self.fail:
            raise RuntimeError("model unavailable")
        self.messages += _history()
        return "done"


@pytest.mark.parametrize("payload", [None, {}, {"prompt": ""}, {"prompt": 5}, "text"])
def test_invalid_payload(payload):
    r = runtime.process_request(payload, "s1")
    assert r["status"] == "error" and r["error_type"] == "invalid_request"


def test_success_reports_tools_and_session(monkeypatch):
    monkeypatch.setattr(runtime, "get_agent", lambda sid: FakeAgent())
    r = runtime.process_request({"prompt": "go"}, "sess-1")
    assert r["status"] == "success" and r["session_id"] == "sess-1"
    assert r["tool_errors"] == 2 and len(r["tool_calls"]) == 3


def test_agent_exception_becomes_clean_error(monkeypatch):
    monkeypatch.setattr(runtime, "get_agent", lambda sid: FakeAgent(fail=True))
    r = runtime.process_request({"prompt": "go"}, "sess-2")
    assert r["status"] == "error" and r["error_type"] == "agent_execution_failed"
    assert "Traceback" not in r["error"]


# ---- workflow / action payloads (no LLM) -----------------------------------
from business_agent.tools.approval import clear_approvals  # noqa: E402
from business_agent.tools.notification import clear_outbox  # noqa: E402
from business_agent.tools.order import clear_orders  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.delenv("SIMULATE_TOOL_FAILURE", raising=False)
    clear_orders(); clear_approvals(); clear_outbox()


PO = {"workflow": "purchase_order", "inputs": {"product": "monitor", "quantity": 3, "department": "HR"}}


def test_workflow_request_success_and_execution_tracking():
    r = runtime.process_request(PO, "w1")
    assert r["status"] == "success" and r["workflow_status"] == "completed"
    assert r["execution_id"].startswith("exe-") and len(r["steps"]) == 5
    g = runtime.process_request({"action": "get_execution", "execution_id": r["execution_id"]}, "w1")
    assert g["execution"]["status"] == "completed" and g["execution"]["kind"] == "workflow"
    listed = runtime.process_request({"action": "list_executions"}, "w1")
    assert any(e["execution_id"] == r["execution_id"] for e in listed["executions"])


def test_workflow_failure_reports_step():
    bad = {"workflow": "purchase_order", "inputs": {**PO["inputs"], "product": "nothing"}}
    r = runtime.process_request(bad, "w2")
    assert r["status"] == "error" and r["workflow_status"] == "failed" and r["failed_step"] == "lookup"
    assert runtime.executions.get(r["execution_id"])["status"] == "failed"


def test_workflow_tool_exception_is_clean(monkeypatch):
    monkeypatch.setenv("SIMULATE_TOOL_FAILURE", "1")
    r = runtime.process_request(PO, "w3")
    assert r["status"] == "error" and r["failed_step"] == "create" and "Traceback" not in str(r)


def test_approval_flow_through_runtime():
    big = {"workflow": "purchase_order", "inputs": {"product": "laptop", "quantity": 2, "department": "Finance"}}
    r1 = runtime.process_request(big, "w4")
    assert r1["workflow_status"] == "pending_approval" and r1["status"] == "success"
    aid = r1["steps"][2]["output"]["approval_id"]
    assert runtime.process_request({"action": "approve", "approval_id": aid}, "w4")["status"] == "success"
    big["inputs"]["approval_id"] = aid
    assert runtime.process_request(big, "w4")["workflow_status"] == "completed"


@pytest.mark.parametrize(
    "payload",
    [
        {"workflow": "nope", "inputs": {}},
        {"workflow": "purchase_order", "inputs": {}},
        {"action": "explode"},
    ],
)
def test_bad_workflow_or_action_is_invalid_request(payload):
    r = runtime.process_request(payload, "w5")
    assert r["status"] == "error" and r["error_type"] == "invalid_request"


def test_unknown_execution_and_approval_ids():
    assert runtime.process_request({"action": "get_execution", "execution_id": "x"}, "w6")["error_type"] == "not_found"
    assert runtime.process_request({"action": "approve", "approval_id": "x"}, "w6")["error_type"] == "not_found"


def test_list_workflows_action():
    r = runtime.process_request({"action": "list_workflows"}, "w7")
    assert {w["name"] for w in r["workflows"]} >= {"purchase_order", "order_status_check"}


def test_agent_run_is_tracked(monkeypatch):
    monkeypatch.setattr(runtime, "get_agent", lambda sid: FakeAgent())
    r = runtime.process_request({"prompt": "go"}, "w8")
    assert runtime.executions.get(r["execution_id"])["status"] == "completed"
