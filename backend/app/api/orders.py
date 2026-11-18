from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import select

from app.api.dependencies import Database, Page, require_staff
from app.models import Order
from app.order_schemas import OrderCreate, OrderRead, OrderStatus
from app.schemas import Identifier
from app.services import orders

router = APIRouter(prefix="/orders", tags=["orders"], dependencies=[Depends(require_staff)])
IdempotencyKey = Annotated[str, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]


@router.post(
    "", status_code=201, response_model=OrderRead,
    responses={200: {"model": OrderRead, "description": "Replay of an existing order"}},
)
def create_order(data: OrderCreate, idempotency_key: IdempotencyKey, db: Database, response: Response):
    try:
        order, created = orders.create_order(db, data, idempotency_key)
    except orders.OrderConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except orders.OrderReferenceNotFound as exc:
        raise HTTPException(404, str(exc)) from None
    if not created:
        response.status_code = 200
    return order


@router.get("", response_model=list[OrderRead])
def list_orders(db: Database, page: Page):
    return db.scalars(select(Order).order_by(Order.id).offset(page.offset).limit(page.limit)).all()


@router.get("/{order_id}", response_model=OrderRead)
def get_order(order_id: Identifier, db: Database):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    return order


def change_status(db: Database, order_id: int, target: OrderStatus) -> Order:
    try:
        return orders.transition_order(db, order_id, target)
    except orders.OrderConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except orders.OrderReferenceNotFound as exc:
        raise HTTPException(404, str(exc)) from None


@router.post("/{order_id}/cancel", response_model=OrderRead)
def cancel_order(order_id: Identifier, db: Database):
    return change_status(db, order_id, "CANCELLED")


@router.post("/{order_id}/fulfill", response_model=OrderRead)
def fulfill_order(order_id: Identifier, db: Database):
    return change_status(db, order_id, "FULFILLED")
