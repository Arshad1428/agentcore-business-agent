"""AgentCore Runtime entry point. Wraps the SAME agent built in agent.py."""
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

settings = load_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("business_agent.runtime")

app = BedrockAgentCoreApp()
_agents: dict[str, object] = {}  # one agent (conversation) per runtime session


def get_agent(session_id: str):
    if session_id not in _agents:
        _agents[session_id] = build_agent(settings)
    return _agents[session_id]


def process_request(payload, session_id: str) -> dict:
    """Pure request handling (testable without the Runtime server)."""
    request_id = uuid.uuid4().hex[:12]
    t0 = time.perf_counter()

    prompt = payload.get("prompt") if isinstance(payload, dict) else None
    if not isinstance(prompt, str) or not prompt.strip():
        log.warning("invalid_request request_id=%s session=%s", request_id, session_id)
        return {
            "status": "error",
            "error_type": "invalid_request",
            "error": 'Payload must be JSON like {"prompt": "<your request>"}.',
            "session_id": session_id,
            "request_id": request_id,
        }

    log.info("request_start request_id=%s session=%s prompt_chars=%d", request_id, session_id, len(prompt))
    try:
        agent = get_agent(session_id)
        start = len(agent.messages)
        result = agent(prompt)
        calls = extract_tool_calls(agent.messages[start:])
    except Exception as exc:  # Runtime/agent/model error: log details, return a clean error
        latency = int((time.perf_counter() - t0) * 1000)
        log.exception("agent_error request_id=%s session=%s latency_ms=%d", request_id, session_id, latency)
        return {
            "status": "error",
            "error_type": "agent_execution_failed",
            "error": f"{type(exc).__name__}: the agent could not complete the request.",
            "session_id": session_id,
            "request_id": request_id,
            "latency_ms": latency,
        }

    latency = int((time.perf_counter() - t0) * 1000)
    for c in calls:
        log.info("tool_call request_id=%s tool=%s status=%s", request_id, c["name"], c["status"])
    tool_errors = sum(1 for c in calls if c["status"] == "error")
    log.info(
        "request_end request_id=%s session=%s tools=%d tool_errors=%d latency_ms=%d",
        request_id, session_id, len(calls), tool_errors, latency,
    )
    return {
        "status": "success",
        "response": str(result),
        "tool_calls": calls,
        "tool_errors": tool_errors,
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
