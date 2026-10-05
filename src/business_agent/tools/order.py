from __future__ import annotations

import uuid

from strands import tool

from business_agent.config import simulated_failure_enabled
from business_agent.data.products import (
    ALLOWED_DEPARTMENTS,
    CURRENCY,
    MAX_ORDER_QUANTITY,
    find_department,
    find_product,
)

# Simulated order store (in-memory, per process). No real purchase happens.
_ORDERS: list[dict] = []


def get_orders() -> list[dict]:
    return list(_ORDERS)


def clear_orders() -> None:
    _ORDERS.clear()


@tool
def create_order(product: str, quantity: int, department: str) -> dict:
    """Create a SIMULATED purchase order. No real purchase is made.

    Call this only when you know the product, a valid quantity and the
    department, and lookup_product showed the product is available. The tool
    re-checks every business rule itself and recomputes the price from the
    catalog, so it may reject a request even if you believe it is valid.

    Args:
        product: Catalog product name, e.g. "monitor".
        quantity: Whole number of units, 1 to 50.
        department: One of Engineering, Finance, HR, Marketing, Operations.

    Returns:
        On success: {"ok": True, "order_id", "product", "quantity",
        "department", "total", "currency", "status": "created"}.
        On rejection: {"ok": False, "error"}. Relay the error; never claim an
        order was created unless ok is True and order_id is present.
    """
    if simulated_failure_enabled():
        raise RuntimeError("Simulated order-system outage (SIMULATE_TOOL_FAILURE).")

    if not isinstance(product, str) or not product.strip():
        return {"ok": False, "error": "product is required."}
    if not isinstance(department, str) or not department.strip():
        return {"ok": False, "error": "department is required."}
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        return {"ok": False, "error": "quantity must be a whole number."}
    if quantity <= 0:
        return {"ok": False, "error": "quantity must be greater than zero."}
    if quantity > MAX_ORDER_QUANTITY:
        return {"ok": False, "error": f"quantity cannot exceed {MAX_ORDER_QUANTITY} per order."}

    dept = find_department(department)
    if dept is None:
        return {"ok": False, "error": f"Unknown department. Allowed: {', '.join(ALLOWED_DEPARTMENTS)}."}

    found = find_product(product)
    if found is None:
        return {"ok": False, "error": f"Product '{product.strip()}' does not exist in the catalog."}
    key, p = found
    if p["stock"] <= 0:
        return {"ok": False, "error": f"{p['name']} is out of stock."}
    if quantity > p["stock"]:
        return {"ok": False, "error": f"Only {p['stock']} {p['name']}(s) in stock; requested {quantity}."}

    order = {
        "ok": True,
        "order_id": f"ORD-{uuid.uuid4().hex[:8].upper()}",
        "product": key,
        "quantity": quantity,
        "department": dept,
        "total": p["unit_price"] * quantity,
        "currency": CURRENCY,
        "status": "created",
    }
    _ORDERS.append(order)
    return order
