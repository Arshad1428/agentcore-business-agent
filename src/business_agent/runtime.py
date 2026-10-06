"""AgentCore Runtime entry point. Wraps the SAME agent built in agent.py.

Payload shapes (all JSON):
    {"prompt": "..."}                                   -> LLM agent (tools chosen by the model)
    {"workflow": "purchase_order", "inputs": {...}}     -> configured workflow, run deterministically
    {"action": "list_workflows"}                        -> available workflows
    {"action": "get_execution", "execution_id": "..."}  -> status of one execution
    {"action": "list_executions"}                       -> recent executions of this session
    {"action": "approve", "approval_id": "..."}         -> manager approval (simulated)
"""
from __future__ import annotations

import logging
import sys
import time
import uuid
from pathlib import Path

if __package__ in (None, ""):  # allow `python src/business_agent/runtime.py` and toolkit packaging
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from business_agent.agent import build_agent, extract_tool_calls
from business_agent.config import load_settings
from business_agent.executions import ExecutionStore, SessionCache
from business_agent.tools.approval import grant_approval
from business_agent.workflows import WorkflowError, list_workflows, run_workflow, validate_inputs

settings = load_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("business_agent.runtime")

app = BedrockAgentCoreApp()
_sessions = SessionCache(
    lambda: build_agent(settings),
    max_sessions=settings.max_sessions,
    ttl_seconds=settings.session_ttl_seconds,
)
executions = ExecutionStore()


def get_agent(session_id: str):
    return _sessions.get(session_id)


def _error(error_type: str, message: str, session_id: str, request_id: str, **extra) -> dict:
    return {"status": "error", "error_type": error_type, "error": message,
            "session_id": session_id, "request_id": request_id, **extra}


def _handle_action(payload: dict, session_id: str, request_id: str) -> dict:
    action = payload.get("action")
    if action == "list_workflows":
        return {"status": "success", "workflows": list_workflows(),
                "session_id": session_id, "request_id": request_id}
    if action == "list_executions":
        return {"status": "success", "executions": executions.list(session_id=session_id),
                "session_id": session_id, "request_id": request_id}
    if action == "get_execution":
        rec = executions.get(str(payload.get("execution_id", "")))
        if rec is None:
            return _error("not_found", "Unknown execution_id.", session_id, request_id)
        return {"status": "success", "execution": rec, "session_id": session_id, "request_id": request_id}
    if action == "approve":
        result = grant_approval(str(payload.get("approval_id", "")))
        if not result["ok"]:
            return _error("not_found", result["error"], session_id, request_id)
        log.info("approval_granted request_id=%s approval_id=%s", request_id, result["approval_id"])
        return {"status": "success", "approval_id": result["approval_id"],
                "approval_status": result["status"], "session_id": session_id, "request_id": request_id}
    return _error("invalid_request",
                  "Unknown action. Use list_workflows, list_executions, get_execution or approve.",
                  session_id, request_id)


def _handle_workflow(payload: dict, session_id: str, request_id: str) -> dict:
    name, inputs = payload.get("workflow"), payload.get("inputs", {})
    t0 = time.perf_counter()
    try:
        eid = None
        validate_inputs(name, inputs)  # reject bad requests before creating an execution
        eid = executions.start("workflow", session_id, name)
        log.info("workflow_start request_id=%s execution=%s workflow=%s", request_id, eid, name)
        report = run_workflow(name, inputs)
    except WorkflowError as exc:
        return _error("invalid_request", str(exc), session_id, request_id)
    except Exception as exc:
        latency = int((time.perf_counter() - t0) * 1000)
        log.exception("workflow_error request_id=%s session=%s", request_id, session_id)
        if eid:
            executions.finish(eid, "failed", error_type=type(exc).__name__)
        return _error("workflow_execution_failed", f"{type(exc).__name__}: the workflow could not complete.",
                      session_id, request_id, execution_id=eid, latency_ms=latency)

    latency = int((time.perf_counter() - t0) * 1000)
    executions.finish(eid, report["status"], failed_step=report["failed_step"], latency_ms=latency)
    return {
        "status": "success" if report["status"] != "failed" else "error",
        "workflow_status": report["status"],
        "workflow": report["workflow"],
        "failed_step": report["failed_step"],
        "steps": report["steps"],
        "execution_id": eid,
        "session_id": session_id,
        "request_id": request_id,
        "latency_ms": latency,
        **({"error_type": "workflow_step_failed"} if report["status"] == "failed" else {}),
    }


def process_request(payload, session_id: str) -> dict:
    """Pure request handling (testable without the Runtime server)."""
    request_id = uuid.uuid4().hex[:12]
    t0 = time.perf_counter()

    if isinstance(payload, dict) and payload.get("action"):
        return _handle_action(payload, session_id, request_id)
    if isinstance(payload, dict) and payload.get("workflow"):
        return _handle_workflow(payload, session_id, request_id)

    prompt = payload.get("prompt") if isinstance(payload, dict) else None
    if not isinstance(prompt, str) or not prompt.strip():
        log.warning("invalid_request request_id=%s session=%s", request_id, session_id)
        return _error(
            "invalid_request",
            'Payload must be JSON like {"prompt": "..."}, {"workflow": "...", "inputs": {...}} '
            'or {"action": "..."}.',
            session_id, request_id,
        )

    eid = executions.start("agent", session_id)
    log.info("request_start request_id=%s execution=%s session=%s prompt_chars=%d",
             request_id, eid, session_id, len(prompt))
    try:
        agent = get_agent(session_id)
        start = len(agent.messages)
        result = agent(prompt)
        calls = extract_tool_calls(agent.messages[start:])
    except Exception as exc:  # Runtime/agent/model error: log details, return a clean error
        latency = int((time.perf_counter() - t0) * 1000)
        log.exception("agent_error request_id=%s session=%s latency_ms=%d", request_id, session_id, latency)
        executions.finish(eid, "failed", error_type=type(exc).__name__, latency_ms=latency)
        return _error("agent_execution_failed",
                      f"{type(exc).__name__}: the agent could not complete the request.",
                      session_id, request_id, latency_ms=latency, execution_id=eid)

    latency = int((time.perf_counter() - t0) * 1000)
    for c in calls:
        log.info("tool_call request_id=%s tool=%s status=%s", request_id, c["name"], c["status"])
    tool_errors = sum(1 for c in calls if c["status"] == "error")
    executions.finish(eid, "completed", tools=len(calls), tool_errors=tool_errors, latency_ms=latency)
    log.info("request_end request_id=%s session=%s tools=%d tool_errors=%d latency_ms=%d",
             request_id, session_id, len(calls), tool_errors, latency)
    return {
        "status": "success",
        "response": str(result),
        "tool_calls": calls,
        "tool_errors": tool_errors,
        "execution_id": eid,
        "session_id": session_id,
        "request_id": request_id,
        "latency_ms": latency,
    }


@app.entrypoint
def handler(payload, context=None):
    session_id = getattr(context, "session_id", None) or f"local-{uuid.uuid4().hex[:8]}"
    return process_request(payload, session_id)


if __name__ == "__main__":
    app.run()  # serves POST /invocations on port 8080 for local Runtime validation
