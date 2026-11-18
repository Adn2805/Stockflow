from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.dependencies import Database, Page, require_staff
from app.models import Inventory, Warehouse
from app.schemas import Identifier, InventoryRead, ReceiptCreate, WarehouseRead
from app.services.inventory import ReceiptReferenceNotFound, StockLimitExceeded, receive_stock

router = APIRouter(tags=["inventory"])


@router.get("/warehouses", response_model=list[WarehouseRead])
def list_warehouses(db: Database, page: Page):
    return db.scalars(select(Warehouse).order_by(Warehouse.id).offset(page.offset).limit(page.limit)).all()


@router.get("/inventory", response_model=list[InventoryRead])
def list_inventory(
    db: Database, page: Page, product_id: Identifier | None = None, warehouse_id: Identifier | None = None
):
    statement = select(Inventory)
    if product_id is not None:
        statement = statement.where(Inventory.product_id == product_id)
    if warehouse_id is not None:
        statement = statement.where(Inventory.warehouse_id == warehouse_id)
    statement = statement.order_by(Inventory.product_id, Inventory.warehouse_id)
    return db.scalars(statement.offset(page.offset).limit(page.limit)).all()


@router.post(
    "/inventory/receipts",
    status_code=201,
    response_model=InventoryRead,
    dependencies=[Depends(require_staff)],
)
def create_receipt(data: ReceiptCreate, db: Database):
    try:
        return receive_stock(db, data)
    except ReceiptReferenceNotFound as exc:
        raise HTTPException(404, str(exc)) from None
    except StockLimitExceeded:
        raise HTTPException(409, "Stock balance exceeds the supported range") from None
