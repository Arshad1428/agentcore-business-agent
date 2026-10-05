"""LLM integration tests. They assert on tool calls, not exact wording.

Skipped by default (they call a real model). Free with Ollama:
    RUN_LLM_TESTS=1 pytest tests/test_agent.py -s
With MODEL_PROVIDER=bedrock they cost tokens.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RUN_LLM_TESTS") != "1", reason="set RUN_LLM_TESTS=1 to run")

from strands import tool  # noqa: E402

from business_agent.agent import build_agent, extract_tool_calls  # noqa: E402
from business_agent.tools import calculate_order_total, lookup_product  # noqa: E402
from business_agent.tools.order import clear_orders, get_orders  # noqa: E402


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("SIMULATE_TOOL_FAILURE", raising=False)
    clear_orders()


def run(prompt, tools=None):
    agent = build_agent(tools=tools)
    result = agent(prompt)
    calls = extract_tool_calls(agent.messages, include_inputs=True)
    print("\nTRACE:", [(c["name"], c.get("input"), c["status"]) for c in calls])
    return str(result), calls


def names(calls):
    return [c["name"] for c in calls]


def test_happy_path():
    _, calls = run("Create an order for 3 monitors for the Engineering department.")
    assert "lookup_product" in names(calls) and "create_order" in names(calls)
    assert names(calls).index("lookup_product") < names(calls).index("create_order")
    orders = get_orders()
    assert len(orders) == 1 and orders[0]["quantity"] == 3 and orders[0]["department"] == "Engineering"


def test_missing_information_asks_instead_of_ordering():
    _, calls = run("Create an order for monitors.")
    assert "create_order" not in names(calls) and get_orders() == []


def test_unknown_product_no_fabricated_order():
    _, calls = run("Order 5 quantum keyboards for Engineering.")
    assert "create_order" not in names(calls) and get_orders() == []


def test_invalid_quantity_creates_nothing():
    run("Order -5 monitors for Engineering.")
    assert get_orders() == []


def test_out_of_scope_uses_no_tools():
    _, calls = run("Write me a poem about the ocean and explain quantum physics.")
    assert calls == [] and get_orders() == []


def test_tool_failure_is_not_reported_as_success():
    @tool
    def create_order(product: str, quantity: int, department: str) -> dict:
        """Create a SIMULATED purchase order. Call only with product, quantity and department.

        Args:
            product: Catalog product name.
            quantity: Whole number of units.
            department: Department name.
        """
        raise RuntimeError("order system down")

    text, calls = run(
        "Create an order for 3 monitors for Engineering.",
        tools=[lookup_product, calculate_order_total, create_order],
    )
    assert any(c["name"] == "create_order" and c["status"] == "error" for c in calls)
    assert "ORD-" not in text and get_orders() == []
