import json
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Inventory, Order, OrderItem, Product, StockMovement, Warehouse
from app.order_schemas import OrderCreate, OrderStatus


class OrderConflict(Exception):
    pass


class OrderReferenceNotFound(Exception):
    pass


def lock_inventory(session: Session, warehouse_id: int, product_ids: list[int]) -> dict[int, Inventory]:
    statement = (
        select(Inventory)
        .where(Inventory.warehouse_id == warehouse_id, Inventory.product_id.in_(product_ids))
        .order_by(Inventory.product_id)
        .with_for_update()
    )
    return {row.product_id: row for row in session.scalars(statement)}


def create_order(session: Session, data: OrderCreate, key: str) -> tuple[Order, bool]:
    items = sorted(data.items, key=lambda item: item.product_id)
    product_ids = [item.product_id for item in items]
    payload = data.model_dump(exclude={"items"})
    payload["items"] = [item.model_dump() for item in items]
    request_hash = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    with session.begin():
        # Conflicting inserts wait for the first transaction to commit or roll back.
        statement = (
            insert(Order)
            .values(customer_reference=data.customer_reference, warehouse_id=data.warehouse_id,
                    idempotency_key=key, request_hash=request_hash, status="RESERVED")
            .on_conflict_do_nothing(index_elements=[Order.idempotency_key])
            .returning(Order)
        )
        order = session.scalars(statement).one_or_none()
        if order is None:
            existing = session.scalars(select(Order).where(Order.idempotency_key == key)).one()
            if existing.request_hash != request_hash:
                raise OrderConflict("Idempotency key was used for a different order")
            return existing, False

        # The deferred foreign key lets key conflicts take precedence over reference errors.
        if session.get(Warehouse, data.warehouse_id) is None:
            raise OrderReferenceNotFound("Warehouse not found")

        prices = dict(session.execute(
            select(Product.id, Product.price).where(Product.id.in_(product_ids))
        ).tuples().all())
        if len(prices) != len(items):
            raise OrderReferenceNotFound("Product not found")

        balances = lock_inventory(session, data.warehouse_id, product_ids)
        for item in items:
            balance = balances.get(item.product_id)
            if balance is None or balance.available < item.quantity:
                raise OrderConflict("Insufficient available stock")

        for item in items:
            balance = balances[item.product_id]
            balance.reserved += item.quantity
            order.items.append(OrderItem(
                product_id=item.product_id, quantity=item.quantity,
                unit_price_snapshot=prices[item.product_id],
            ))
            record_movement(session, order, balance, "RESERVATION", 0, item.quantity)
    return order, True


def record_movement(
    session: Session, order: Order, balance: Inventory, movement_type: str,
    delta_on_hand: int, delta_reserved: int,
) -> None:
    session.add(StockMovement(
        order_id=order.id, product_id=balance.product_id, warehouse_id=balance.warehouse_id,
        movement_type=movement_type, delta_on_hand=delta_on_hand, delta_reserved=delta_reserved,
    ))


def transition_order(session: Session, order_id: int, target: OrderStatus) -> Order:
    with session.begin():
        order = session.get(Order, order_id, with_for_update=True)
        if order is None:
            raise OrderReferenceNotFound("Order not found")
        if order.status == target:
            return order
        if order.status != "RESERVED":
            raise OrderConflict("Order has already reached a different terminal status")

        balances = lock_inventory(session, order.warehouse_id, [item.product_id for item in order.items])
        movement_type = "FULFILLMENT" if target == "FULFILLED" else "CANCELLATION"
        for item in order.items:
            balance = balances[item.product_id]
            balance.reserved -= item.quantity
            delta_on_hand = -item.quantity if target == "FULFILLED" else 0
            balance.on_hand += delta_on_hand
            record_movement(session, order, balance, movement_type, delta_on_hand, -item.quantity)
        order.status = target
    return order
