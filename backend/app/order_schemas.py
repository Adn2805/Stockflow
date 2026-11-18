from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas import Identifier, MAX_BIGINT

OrderStatus = Literal["RESERVED", "FULFILLED", "CANCELLED"]


class OrderItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: Annotated[Identifier, Field(strict=True)]
    quantity: Annotated[int, Field(strict=True, gt=0, le=MAX_BIGINT)]


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_reference: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200,
                               pattern=r"^[^\x00]*$")
    ]
    warehouse_id: Annotated[Identifier, Field(strict=True)]
    items: Annotated[list[OrderItemCreate], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def unique_products(self):
        if len({item.product_id for item in self.items}) != len(self.items):
            raise ValueError("Each product may appear only once per order")
        return self


class OrderItemRead(OrderItemCreate):
    model_config = ConfigDict(from_attributes=True)
    unit_price_snapshot: Decimal


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_reference: str
    warehouse_id: int
    status: OrderStatus
    created_at: datetime
    items: list[OrderItemRead]
