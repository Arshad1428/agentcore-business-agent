from __future__ import annotations

from strands import tool

from business_agent.data.products import CURRENCY, MAX_ORDER_QUANTITY


@tool
def calculate_order_total(unit_price: float, quantity: int) -> dict:
    """Calculate the total cost of an order line (unit_price x quantity).

    Use this to quote a total to the user. Use the unit_price returned by
    lookup_product; do not use a price from memory. This tool only does
    arithmetic; it does not create an order.

    Args:
        unit_price: Price of one unit, a non-negative number from lookup_product.
        quantity: Number of units, a positive whole number.

    Returns:
        On success: {"ok": True, "unit_price", "quantity", "total", "currency"}.
        On invalid input: {"ok": False, "error"}.
    """
    if isinstance(unit_price, bool) or not isinstance(unit_price, (int, float)):
        return {"ok": False, "error": "unit_price must be a number."}
    if unit_price < 0:
        return {"ok": False, "error": "unit_price cannot be negative."}
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        return {"ok": False, "error": "quantity must be a whole number."}
    if quantity <= 0:
        return {"ok": False, "error": "quantity must be greater than zero."}
    if quantity > MAX_ORDER_QUANTITY:
        return {"ok": False, "error": f"quantity cannot exceed {MAX_ORDER_QUANTITY} per order."}
    return {
        "ok": True,
        "unit_price": unit_price,
        "quantity": quantity,
        "total": round(unit_price * quantity, 2),
        "currency": CURRENCY,
    }
