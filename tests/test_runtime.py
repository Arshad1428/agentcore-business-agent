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
