"""DEMO DATA ONLY. Fictional products, prices (INR) and stock levels."""
from __future__ import annotations

CURRENCY = "INR"
MAX_ORDER_QUANTITY = 50
ALLOWED_DEPARTMENTS = ("Engineering", "Finance", "HR", "Marketing", "Operations")

PRODUCTS: dict[str, dict] = {
    "monitor": {"name": "Monitor", "unit_price": 15000, "stock": 25},
    "keyboard": {"name": "Keyboard", "unit_price": 2500, "stock": 100},
    "mouse": {"name": "Mouse", "unit_price": 800, "stock": 0},  # out of stock on purpose
    "laptop": {"name": "Laptop", "unit_price": 85000, "stock": 5},
}


def find_product(name: str) -> tuple[str, dict] | None:
    """Case-insensitive lookup; tolerates a simple plural ('monitors')."""
    key = (name or "").strip().lower()
    if not key:
        return None
    if key in PRODUCTS:
        return key, PRODUCTS[key]
    if key.endswith("s") and key[:-1] in PRODUCTS:
        return key[:-1], PRODUCTS[key[:-1]]
    return None


def find_department(name: str) -> str | None:
    key = (name or "").strip().lower()
    for dept in ALLOWED_DEPARTMENTS:
        if dept.lower() == key:
            return dept
    return None
