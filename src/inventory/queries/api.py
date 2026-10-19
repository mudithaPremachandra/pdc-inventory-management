

from datetime import datetime

from fastapi import Depends, FastAPI, Query, Request, status
from fastapi.responses import JSONResponse

from inventory.auth.permissions import ROLE_PERMISSIONS, Perm, Principal, current_principal, require
from inventory.db import get_pool
from inventory.domain.errors import DomainError, InvalidInput, NotFound
from inventory.eventstore.store import EventStore
from inventory.projections.rebuild import rebuild
from inventory.queries import queries
from inventory.queries.time_travel import product_as_of

app = FastAPI(title="Inventory query API (read side)")


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    code = {NotFound: 404, InvalidInput: 422}.get(type(exc), status.HTTP_400_BAD_REQUEST)
    return JSONResponse(status_code=code, content={"detail": str(exc), "error": type(exc).__name__})


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "side": "query"}


@app.get("/me")
def me(who: Principal = Depends(current_principal)) -> dict:
    return {"username": who.username, "role": who.role, "permissions": sorted(ROLE_PERMISSIONS[who.role])}


@app.get("/status")
def projection_status(_: Principal = Depends(current_principal)) -> dict:
    return queries.projection_status(get_pool())


@app.get("/products")
def list_products(
    search: str | None = None,
    include_discontinued: bool = False,
    _: Principal = Depends(require(Perm.INVENTORY_READ)),
) -> list[dict]:
    return queries.list_products(get_pool(), search, include_discontinued)


@app.get("/products/{sku}")
def get_product(sku: str, _: Principal = Depends(require(Perm.INVENTORY_READ))) -> dict:
    return queries.get_product(get_pool(), sku)


@app.get("/products/{sku}/history")
def stock_history(
    sku: str, limit: int = Query(50, ge=1, le=500), _: Principal = Depends(require(Perm.INVENTORY_READ))
) -> list[dict]:
    return queries.stock_history(get_pool(), sku, limit)


@app.get("/products/{sku}/as-of")
def product_at(sku: str, at: datetime, _: Principal = Depends(require(Perm.INVENTORY_READ))) -> dict:
    return product_as_of(EventStore(get_pool()), sku, at)


@app.get("/reports/low-stock")
def low_stock(_: Principal = Depends(require(Perm.INVENTORY_READ))) -> list[dict]:
    return queries.low_stock(get_pool())


@app.get("/reports/valuation")
def valuation(_: Principal = Depends(require(Perm.REPORTS_READ))) -> dict:
    return queries.stock_valuation(get_pool())


@app.get("/users")
def list_users(_: Principal = Depends(require(Perm.USERS_MANAGE))) -> list[dict]:
    return queries.list_users(get_pool())


@app.get("/events")
def event_log(
    stream: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    _: Principal = Depends(require(Perm.EVENTS_READ)),
) -> list[dict]:
    return queries.event_log(get_pool(), stream, limit)


@app.post("/admin/rebuild-projections")
def rebuild_projections(_: Principal = Depends(require(Perm.PROJECTIONS_REBUILD))) -> dict:
    return rebuild(get_pool())
