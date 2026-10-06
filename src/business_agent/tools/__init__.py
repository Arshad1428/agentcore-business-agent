from business_agent.tools.approval import request_approval
from business_agent.tools.calculator import calculate_order_total
from business_agent.tools.notification import send_notification
from business_agent.tools.order import create_order, get_order_status
from business_agent.tools.product_lookup import lookup_product
from business_agent.tools.workflow_tool import run_workflow

# Tools the workflow engine may call as steps (no run_workflow: avoids recursion).
_STEP_TOOLS = [
    lookup_product,
    calculate_order_total,
    request_approval,
    create_order,
    get_order_status,
    send_notification,
]
WORKFLOW_TOOLS = {t.tool_name: t for t in _STEP_TOOLS}

# Tools the LLM agent can call directly.
ALL_TOOLS = [
    lookup_product,
    calculate_order_total,
    request_approval,
    create_order,
    get_order_status,
    run_workflow,
]

__all__ = [
    "lookup_product", "calculate_order_total", "request_approval", "create_order",
    "get_order_status", "send_notification", "run_workflow", "ALL_TOOLS", "WORKFLOW_TOOLS",
]
