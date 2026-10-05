"""Deterministic tool tests. No LLM, no AWS, no cost."""
import pytest

from business_agent.tools import calculate_order_total, create_order, lookup_product
from business_agent.tools.order import clear_orders, get_orders


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("SIMULATE_TOOL_FAILURE", raising=False)
    clear_orders()


def test_lookup_known_product():
    r = lookup_product("monitor")
    assert r["ok"] and r["unit_price"] == 15000 and r["available"] is True


def test_lookup_plural_and_case():
    assert lookup_product("  Monitors ")["product"] == "monitor"


def test_lookup_unknown_product_has_no_price():
    r = lookup_product("quantum keyboard")
    assert r["ok"] is False and "unit_price" not in r


def test_lookup_out_of_stock():
    r = lookup_product("mouse")
    assert r["ok"] and r["available"] is False


def test_calculate_total():
    assert calculate_order_total(15000, 3)["total"] == 45000


@pytest.mark.parametrize("qty", [0, -5, 51, True, 2.5])
def test_calculate_rejects_bad_quantity(qty):
    assert calculate_order_total(15000, qty)["ok"] is False


def test_calculate_rejects_bad_price():
    assert calculate_order_total(-1, 2)["ok"] is False
    assert calculate_order_total("abc", 2)["ok"] is False


def test_create_order_happy_path():
    r = create_order("monitor", 3, "engineering")
    assert r["ok"] and r["status"] == "created" and r["order_id"].startswith("ORD-")
    assert r["department"] == "Engineering" and r["total"] == 45000
    assert len(get_orders()) == 1


@pytest.mark.parametrize(
    "args",
    [
        ("monitor", -5, "Engineering"),
        ("monitor", 0, "Engineering"),
        ("monitor", 999, "Engineering"),
        ("monitor", 3, ""),
        ("monitor", 3, "Narnia"),
        ("quantum keyboard", 5, "Engineering"),
        ("mouse", 1, "Engineering"),  # out of stock
        ("laptop", 6, "Engineering"),  # exceeds stock
        ("", 1, "Engineering"),
    ],
)
def test_create_order_rejections(args):
    r = create_order(*args)
    assert r["ok"] is False and "error" in r
    assert get_orders() == []


def test_simulated_failure_raises(monkeypatch):
    monkeypatch.setenv("SIMULATE_TOOL_FAILURE", "1")
    with pytest.raises(RuntimeError):
        create_order("monitor", 1, "Engineering")
    assert get_orders() == []
