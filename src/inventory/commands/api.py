from contextlib import asynccontextmanager
from decimal import Decimal

from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from inventory.auth.permissions import Perm, Principal, require
from inventory.auth.routes import router as auth_router
from inventory.auth.routes import seed_admin
from inventory.commands.commands import (
    AdjustStock,
    DiscontinueProduct,
    DispatchStock,
    ReceiveStock,
    RegisterProduct,
    UpdateProductDetails,
)
from inventory.commands.handlers import CommandHandler, CommandResult
from inventory.db import get_pool
from inventory.domain.errors import (
    AlreadyExists,
    ConcurrencyError,
    DomainError,
    InsufficientStock,
    InvalidInput,
    NotFound,
)
from inventory.eventstore.repository import AggregateRepository
from inventory.eventstore.store import EventStore


def get_handler() -> CommandHandler:
    return CommandHandler(AggregateRepository(EventStore(get_pool())))


@asynccontextmanager
async def lifespan(_: FastAPI):
    seed_admin(get_handler())
    yield


app = FastAPI(title="Inventory command API (write side)", lifespan=lifespan)
app.include_router(auth_router)

ERROR_STATUS = {
    NotFound: status.HTTP_404_NOT_FOUND,
    AlreadyExists: status.HTTP_409_CONFLICT,
    ConcurrencyError: status.HTTP_409_CONFLICT,
    InsufficientStock: status.HTTP_409_CONFLICT,
    InvalidInput: status.HTTP_422_UNPROCESSABLE_ENTITY,
}


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    code = ERROR_STATUS.get(type(exc), status.HTTP_400_BAD_REQUEST)
    return JSONResponse(status_code=code, content={"detail": str(exc), "error": type(exc).__name__})


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "side": "command"}


# --- request bodies ---------------------------------------------------------------


class RegisterProductIn(BaseModel):
    sku: str
    name: str
    unit_price: Decimal = Field(ge=0)
    reorder_level: int = Field(ge=0)
    category: str | None = None


class UpdateProductIn(BaseModel):
    name: str | None = None
    category: str | None = None
    unit_price: Decimal | None = Field(default=None, ge=0)
    reorder_level: int | None = Field(default=None, ge=0)


class StockMovementIn(BaseModel):
    quantity: int
    reference: str | None = None


class AdjustStockIn(BaseModel):
    quantity_change: int
    reason: str


class DiscontinueIn(BaseModel):
    reason: str | None = None


# --- endpoints: one per command -------------------------------------------------------
# 202 Accepted: the events are stored, but the read side catches up asynchronously.


@app.post("/products", status_code=202)
def register_product(
    body: RegisterProductIn,
    who: Principal = Depends(require(Perm.PRODUCT_MANAGE)),
    handler: CommandHandler = Depends(get_handler),
) -> CommandResult:
    return handler.handle(RegisterProduct(**body.model_dump()), who.username)


@app.patch("/products/{sku}", status_code=202)
def update_product(
    sku: str,
    body: UpdateProductIn,
    who: Principal = Depends(require(Perm.PRODUCT_MANAGE)),
    handler: CommandHandler = Depends(get_handler),
) -> CommandResult:
    return handler.handle(UpdateProductDetails(sku=sku, **body.model_dump()), who.username)


@app.post("/products/{sku}/receive", status_code=202)
def receive_stock(
    sku: str,
    body: StockMovementIn,
    who: Principal = Depends(require(Perm.STOCK_RECEIVE)),
    handler: CommandHandler = Depends(get_handler),
) -> CommandResult:
    return handler.handle(ReceiveStock(sku=sku, **body.model_dump()), who.username)


@app.post("/products/{sku}/dispatch", status_code=202)
def dispatch_stock(
    sku: str,
    body: StockMovementIn,
    who: Principal = Depends(require(Perm.STOCK_DISPATCH)),
    handler: CommandHandler = Depends(get_handler),
) -> CommandResult:
    return handler.handle(DispatchStock(sku=sku, **body.model_dump()), who.username)


@app.post("/products/{sku}/adjust", status_code=202)
def adjust_stock(
    sku: str,
    body: AdjustStockIn,
    who: Principal = Depends(require(Perm.STOCK_ADJUST)),
    handler: CommandHandler = Depends(get_handler),
) -> CommandResult:
    return handler.handle(AdjustStock(sku=sku, **body.model_dump()), who.username)


@app.post("/products/{sku}/discontinue", status_code=202)
def discontinue_product(
    sku: str,
    body: DiscontinueIn,
    who: Principal = Depends(require(Perm.PRODUCT_MANAGE)),
    handler: CommandHandler = Depends(get_handler),
) -> CommandResult:
    return handler.handle(DiscontinueProduct(sku=sku, **body.model_dump()), who.username)
