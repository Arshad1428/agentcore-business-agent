"""Builds the single Strands agent: model + system prompt + tools.

No AWS deployment logic here. The Runtime wrapper (runtime.py) imports this.
"""
from __future__ import annotations

from strands import Agent

from business_agent.config import Settings, load_settings
from business_agent.data.products import ALLOWED_DEPARTMENTS, APPROVAL_THRESHOLD, CURRENCY, MAX_ORDER_QUANTITY
from business_agent.tools import ALL_TOOLS

SYSTEM_PROMPT = f"""You are the Purchase Order Assistant for a company's internal procurement desk.

ROLE
You handle only these tasks: looking up catalog products, quoting prices and order totals, and creating SIMULATED purchase orders for internal departments.

TOOLS (the only source of business data)
- lookup_product: get price and availability. Always use it before quoting a price or creating an order.
- calculate_order_total: compute totals from the unit price returned by lookup_product.
- request_approval: orders with a total above the approval threshold need manager approval before create_order. Call it with the total and department; if approved is false, do NOT create the order: give the user the approval_id and say a manager must approve it.
- create_order: create the simulated order (pass approval_id for orders above the threshold).
- get_order_status: look up an existing order by order_id.
- run_workflow: run the configured "purchase_order" workflow (lookup, quote, approval, create, notify) in one call when you have product, quantity and department, or "order_status_check" with an order_id. Prefer it for a complete order request.
You decide which tools are needed. If a question needs no tool (for example asking what you can do), answer directly.

RULES
- Never invent products, prices, stock levels, departments or order IDs. If a tool says a product does not exist, say so and do not guess a price.
- To create an order you need all three: product, quantity, department. If any is missing, ask the user for it. Do not assume a department or quantity.
- Valid departments: {', '.join(ALLOWED_DEPARTMENTS)}. Quantity must be a whole number from 1 to {MAX_ORDER_QUANTITY}. Tools enforce these rules; if a tool rejects a request, explain the reason plainly.
- Only create an order if lookup_product shows the product is available.
- Orders above {APPROVAL_THRESHOLD} {CURRENCY} need an APPROVED approval_id. You can never approve requests yourself.
- Report tool failures honestly. Never say an order was created unless create_order returned ok=true with an order_id, or run_workflow returned status "completed". If a tool errors, say the order was NOT created.
- Orders are simulated. You cannot make real purchases, process payments, approvals, refunds or returns.

OUT OF SCOPE
Politely decline anything else (general knowledge, coding, legal/HR advice, other business systems) and restate what you can help with.

STYLE
Be brief. After creating an order, confirm product, quantity, department, total and order ID.
"""


def build_model(settings: Settings):
    """Model provider selection. Imports are lazy so unused providers need no install."""
    if settings.model_provider == "bedrock":
        from strands.models import BedrockModel

        return BedrockModel(
            model_id=settings.bedrock_model_id,
            region_name=settings.aws_region,
            temperature=0.0,
        )
    from strands.models.ollama import OllamaModel  # needs: pip install 'strands-agents[ollama]'

    return OllamaModel(settings.ollama_host, model_id=settings.ollama_model_id, temperature=0.0)


def build_agent(settings: Settings | None = None, model=None, tools=None) -> Agent:
    settings = settings or load_settings()
    return Agent(
        model=model if model is not None else build_model(settings),
        system_prompt=SYSTEM_PROMPT,
        tools=list(tools) if tools is not None else list(ALL_TOOLS),
        callback_handler=None,  # we report via logs/trace instead of streaming to stdout
    )


def _payload_is_error(content) -> bool:
    for item in content or []:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("json"), dict) and item["json"].get("ok") is False:
            return True
        text = item.get("text")
        if isinstance(text, str) and ('"ok": false' in text.lower() or "'ok': false" in text.lower()):
            return True
    return False


def extract_tool_calls(messages, include_inputs: bool = False) -> list[dict]:
    """Reads the Strands message history and returns the tools the model used.

    status: "success" | "error" (tool raised, or returned ok=false) | "unknown".
    """
    calls: dict[str, dict] = {}
    order: list[str] = []
    for msg in messages or []:
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if "toolUse" in block:
                tu = block["toolUse"]
                entry = {"name": tu.get("name"), "status": "unknown"}
                if include_inputs:
                    entry["input"] = tu.get("input", {})
                calls[tu.get("toolUseId")] = entry
                order.append(tu.get("toolUseId"))
            elif "toolResult" in block:
                tr = block["toolResult"]
                entry = calls.get(tr.get("toolUseId"))
                if entry is not None:
                    failed = tr.get("status") == "error" or _payload_is_error(tr.get("content"))
                    entry["status"] = "error" if failed else "success"
    return [calls[i] for i in order]
