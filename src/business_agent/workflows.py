"""Declarative, configurable workflows executed step by step over the same tools.

A workflow is plain data (see WORKFLOWS). The engine runs each step's tool directly
and deterministically, passes outputs forward via references, and stops on the first
failure or on a "pause" condition (e.g. waiting for manager approval).

References inside a step's `args`:
    "$input.<name>"            value from the workflow inputs
    "$steps.<step_id>.<field>" field from an earlier step's output
Anything else is a literal value.
"""
from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger("business_agent.workflows")

WORKFLOWS: dict[str, dict] = {
    "purchase_order": {
        "description": (
            "Quote, approve (if the total is above the threshold), create a simulated "
            "purchase order and notify the department."
        ),
        "inputs": ["product", "quantity", "department"],
        "optional_inputs": ["approval_id"],
        "steps": [
            {"id": "lookup", "tool": "lookup_product", "args": {"product_name": "$input.product"}},
            {
                "id": "quote",
                "tool": "calculate_order_total",
                "args": {"unit_price": "$steps.lookup.unit_price", "quantity": "$input.quantity"},
            },
            {
                "id": "approval",
                "tool": "request_approval",
                "args": {
                    "amount": "$steps.quote.total",
                    "department": "$input.department",
                    "approval_id": "$input.approval_id",
                },
                # Pause (not fail) while approval is pending; resume by re-running with approval_id.
                "pause_if": {"field": "approved", "equals": False, "status": "pending_approval"},
            },
            {
                "id": "create",
                "tool": "create_order",
                "args": {
                    "product": "$input.product",
                    "quantity": "$input.quantity",
                    "department": "$input.department",
                    "approval_id": "$steps.approval.approval_id",
                },
            },
            {
                "id": "notify",
                "tool": "send_notification",
                "args": {
                    "recipient": "$input.department",
                    "event": "order_created",
                    "reference": "$steps.create.order_id",
                },
            },
        ],
    },
    "order_status_check": {
        "description": "Look up the status of an existing order.",
        "inputs": ["order_id"],
        "steps": [
            {"id": "status", "tool": "get_order_status", "args": {"order_id": "$input.order_id"}},
        ],
    },
}


class WorkflowError(ValueError):
    """Bad workflow name or inputs (a caller error, not a runtime failure)."""


def list_workflows() -> list[dict]:
    return [
        {
            "name": name,
            "description": wf["description"],
            "inputs": wf["inputs"],
            "optional_inputs": wf.get("optional_inputs", []),
            "steps": [s["id"] for s in wf["steps"]],
        }
        for name, wf in WORKFLOWS.items()
    ]


def _resolve(value: Any, inputs: dict, outputs: dict) -> Any:
    if not (isinstance(value, str) and value.startswith("$")):
        return value
    parts = value[1:].split(".")
    if parts[0] == "input" and len(parts) == 2:
        return inputs.get(parts[1])
    if parts[0] == "steps" and len(parts) == 3:
        return outputs.get(parts[1], {}).get(parts[2])
    raise WorkflowError(f"Bad reference '{value}' in workflow definition.")


def validate_inputs(name: str, inputs: Any) -> dict:
    if name not in WORKFLOWS:
        raise WorkflowError(f"Unknown workflow '{name}'. Available: {', '.join(WORKFLOWS)}.")
    if not isinstance(inputs, dict):
        raise WorkflowError("inputs must be a JSON object.")
    wf = WORKFLOWS[name]
    missing = [k for k in wf["inputs"] if inputs.get(k) in (None, "")]
    if missing:
        raise WorkflowError(f"Workflow '{name}' is missing inputs: {', '.join(missing)}.")
    allowed = set(wf["inputs"]) | set(wf.get("optional_inputs", []))
    unexpected = sorted(set(inputs) - allowed)
    if unexpected:
        raise WorkflowError(f"Unexpected inputs for '{name}': {', '.join(unexpected)}.")
    return inputs


def run_workflow(name: str, inputs: dict, registry: dict | None = None) -> dict:
    """Run a workflow. Returns a report; never raises for tool failures.

    status: "completed" | "failed" | "pending_approval".
    Raises WorkflowError only for an unknown workflow or invalid inputs.
    """
    inputs = validate_inputs(name, inputs)
    if registry is None:
        from business_agent.tools import WORKFLOW_TOOLS

        registry = WORKFLOW_TOOLS

    wf = WORKFLOWS[name]
    outputs: dict[str, dict] = {}
    report: list[dict] = []
    status, failed_step, t0 = "completed", None, time.perf_counter()

    for step in wf["steps"]:
        sid, tool_name = step["id"], step["tool"]
        tool_fn = registry.get(tool_name)
        if status != "completed":
            report.append({"id": sid, "tool": tool_name, "status": "skipped"})
            continue
        if tool_fn is None:
            status, failed_step = "failed", sid
            report.append({"id": sid, "tool": tool_name, "status": "error", "error": "tool not registered"})
            continue

        args = {k: _resolve(v, inputs, outputs) for k, v in step["args"].items()}
        args = {k: v for k, v in args.items() if v is not None}  # optional args left unset
        t_step = time.perf_counter()
        try:
            out = tool_fn(**args)
        except Exception as exc:  # tool crashed: record it, stop the workflow
            log.exception("workflow_step_exception workflow=%s step=%s", name, sid)
            status, failed_step = "failed", sid
            report.append({"id": sid, "tool": tool_name, "status": "error",
                           "error": f"{type(exc).__name__}: tool raised an exception"})
            continue

        ms = int((time.perf_counter() - t_step) * 1000)
        outputs[sid] = out if isinstance(out, dict) else {"value": out}
        if not (isinstance(out, dict) and out.get("ok") is True):
            err = out.get("error", "tool returned ok=false") if isinstance(out, dict) else "bad tool output"
            status, failed_step = "failed", sid
            report.append({"id": sid, "tool": tool_name, "status": "error", "error": err, "ms": ms})
            continue

        report.append({"id": sid, "tool": tool_name, "status": "success", "output": outputs[sid], "ms": ms})
        pause = step.get("pause_if")
        if pause and out.get(pause["field"]) == pause["equals"]:
            status = pause["status"]

    log.info("workflow_end workflow=%s status=%s failed_step=%s latency_ms=%d",
             name, status, failed_step, int((time.perf_counter() - t0) * 1000))
    return {"workflow": name, "status": status, "failed_step": failed_step, "steps": report}
