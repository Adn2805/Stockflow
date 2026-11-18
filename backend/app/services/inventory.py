from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Inventory, Product, StockMovement, Warehouse
from app.schemas import MAX_BIGINT, ReceiptCreate


class StockLimitExceeded(Exception):
    pass


class ReceiptReferenceNotFound(Exception):
    pass


def receive_stock(session: Session, receipt: ReceiptCreate) -> Inventory:
    with session.begin():
        if session.get(Product, receipt.product_id) is None:
            raise ReceiptReferenceNotFound("Product not found")
        if session.get(Warehouse, receipt.warehouse_id) is None:
            raise ReceiptReferenceNotFound("Warehouse not found")

        incoming = insert(Inventory).values(
            product_id=receipt.product_id, warehouse_id=receipt.warehouse_id, on_hand=receipt.quantity
        )
        # PostgreSQL evaluates the increment against the current conflicting row.
        statement = incoming.on_conflict_do_update(
            index_elements=[Inventory.product_id, Inventory.warehouse_id],
            set_={"on_hand": Inventory.on_hand + incoming.excluded.on_hand},
            where=Inventory.on_hand <= MAX_BIGINT - receipt.quantity,
        ).returning(Inventory)
        inventory = session.scalars(statement).one_or_none()
        if inventory is None:
            raise StockLimitExceeded

        session.add(StockMovement(
            product_id=receipt.product_id,
            warehouse_id=receipt.warehouse_id,
            delta_on_hand=receipt.quantity,
            delta_reserved=0,
            movement_type="RECEIPT",
        ))
    return inventory
