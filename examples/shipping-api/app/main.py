from typing import Annotated

from fastapi import FastAPI, Query

from .shipping import shipping_cost

app = FastAPI(title="Shipping Quote Demo")


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/quote")
def quote(subtotal_cents: Annotated[int, Query(ge=0)]):
    shipping = shipping_cost(subtotal_cents)
    return {"subtotal_cents": subtotal_cents, "shipping_cents": shipping,
            "total_cents": subtotal_cents + shipping}
