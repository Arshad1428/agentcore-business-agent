from __future__ import annotations

from strands import tool

# Simulated outbox (in-memory). Swap for Amazon SES/SNS in a real deployment.
_OUTBOX: list[dict] = []


def get_outbox() -> list[dict]:
    return list(_OUTBOX)


def clear_outbox() -> None:
    _OUTBOX.clear()


@tool
def send_notification(recipient: str, event: str, reference: str) -> dict:
    """Send a SIMULATED notification about a business event. Nothing is really sent.

    Args:
        recipient: Department or team to notify.
        event: Event name, e.g. "order_created".
        reference: Related id, e.g. the order_id.

    Returns:
        {"ok": True, "notification_id"} or {"ok": False, "error"}.
    """
    for name, val in (("recipient", recipient), ("event", event), ("reference", reference)):
        if not isinstance(val, str) or not val.strip():
            return {"ok": False, "error": f"{name} is required."}
    _OUTBOX.append({"recipient": recipient.strip(), "event": event.strip(), "reference": reference.strip()})
    return {"ok": True, "notification_id": f"NTF-{len(_OUTBOX):04d}", "recipient": recipient.strip()}
