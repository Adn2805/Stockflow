from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

MAX_BIGINT = 2**63 - 1
Identifier = Annotated[int, Field(gt=0, le=MAX_BIGINT)]
Sku = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1,
                                      max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200,
                                       pattern=r"^[^\x00]*$")]
Description = Annotated[str, StringConstraints(max_length=2000, pattern=r"^[^\x00]*$")]
Price = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: Sku
    name: Name
    description: Description | None = None
    price: Price


class ProductPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: Sku | None = None
    name: Name | None = None
    description: Description | None = None
    price: Price | None = None

    @model_validator(mode="after")
    def validate_patch(self):
        if not self.model_fields_set:
            raise ValueError("Supply at least one field to update")
        if any(getattr(self, name) is None for name in self.model_fields_set - {"description"}):
            raise ValueError("Only description may be null")
        return self


class ProductRead(ProductCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class ReceiptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: Annotated[Identifier, Field(strict=True)]
    warehouse_id: Annotated[Identifier, Field(strict=True)]
    quantity: Annotated[int, Field(strict=True, gt=0, le=MAX_BIGINT)]


class InventoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_id: int
    warehouse_id: int
    on_hand: int
    reserved: int
    available: int


class WarehouseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    location: str
