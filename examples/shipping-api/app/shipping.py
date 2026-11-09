"""Shipping quotes use integer cents to avoid floating-point money arithmetic."""

FREE_SHIPPING_THRESHOLD = 5000
STANDARD_SHIPPING = 599


def shipping_cost(subtotal_cents: int) -> int:
    if subtotal_cents < 0:
        raise ValueError("Subtotal cannot be negative")
    if subtotal_cents > FREE_SHIPPING_THRESHOLD:
        return 0
    return STANDARD_SHIPPING
