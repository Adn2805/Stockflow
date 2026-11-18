from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text

from app.api.dependencies import Database, Page, require_staff
from app.models import StockMovement
from app.schemas import Identifier

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(require_staff)])


class MovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int
    warehouse_id: int
    order_id: int | None
    movement_type: str
    delta_on_hand: int
    delta_reserved: int
    created_at: datetime


class Discrepancy(BaseModel):
    product_id: int
    warehouse_id: int
    actual_on_hand: int | None
    actual_reserved: int | None
    expected_on_hand: int
    expected_reserved: int


@router.get("/stock-movements", response_model=list[MovementRead])
def list_movements(
    db: Database, page: Page, product_id: Identifier | None = None,
    warehouse_id: Identifier | None = None,
):
    statement = select(StockMovement)
    if product_id is not None:
        statement = statement.where(StockMovement.product_id == product_id)
    if warehouse_id is not None:
        statement = statement.where(StockMovement.warehouse_id == warehouse_id)
    return db.scalars(
        statement.order_by(StockMovement.id.desc()).offset(page.offset).limit(page.limit)
    ).all()


RECONCILIATION = text("""
    WITH ledger AS (
        SELECT product_id, warehouse_id,
               SUM(delta_on_hand) AS expected_on_hand,
               SUM(delta_reserved) AS expected_reserved
        FROM stock_movements
        GROUP BY product_id, warehouse_id
    )
    SELECT product_id, warehouse_id,
           inventory.on_hand AS actual_on_hand, inventory.reserved AS actual_reserved,
           COALESCE(ledger.expected_on_hand, 0) AS expected_on_hand,
           COALESCE(ledger.expected_reserved, 0) AS expected_reserved
    FROM inventory FULL JOIN ledger USING (product_id, warehouse_id)
    WHERE inventory.on_hand IS DISTINCT FROM COALESCE(ledger.expected_on_hand, 0)
       OR inventory.reserved IS DISTINCT FROM COALESCE(ledger.expected_reserved, 0)
    ORDER BY product_id, warehouse_id
    LIMIT :limit OFFSET :offset
""")


@router.get("/reconciliation", response_model=list[Discrepancy])
def reconcile(db: Database, page: Page):
    # One SQL statement compares inventory and ledger from the same MVCC snapshot.
    return db.execute(RECONCILIATION, {"limit": page.limit, "offset": page.offset}).mappings().all()
