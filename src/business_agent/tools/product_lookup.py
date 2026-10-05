from __future__ import annotations

from strands import tool

from business_agent.data.products import CURRENCY, PRODUCTS, find_product


@tool
def lookup_product(product_name: str) -> dict:
    """Look up ONE product in the internal catalog.

    Use this first whenever you need a product's unit price or availability.
    Never guess or recall prices; this is the only source of catalog data.

    Args:
        product_name: Product name as the user said it, e.g. "monitor" or "keyboards".

    Returns:
        On success: {"ok": True, "product", "display_name", "unit_price",
        "currency", "available", "stock"}.
        If the product is not in the catalog: {"ok": False, "error",
        "known_products"}. Do not invent a price in that case.
    """
    if not isinstance(product_name, str) or not product_name.strip():
        return {"ok": False, "error": "product_name must be a non-empty string.", "known_products": sorted(PRODUCTS)}
    found = find_product(product_name)
    if found is None:
        return {
            "ok": False,
            "error": f"Product '{product_name.strip()}' does not exist in the catalog.",
            "known_products": sorted(PRODUCTS),
        }
    key, p = found
    return {
        "ok": True,
        "product": key,
        "display_name": p["name"],
        "unit_price": p["unit_price"],
        "currency": CURRENCY,
        "available": p["stock"] > 0,
        "stock": p["stock"],
    }
