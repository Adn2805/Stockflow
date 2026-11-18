from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint,
    Identity, Index, Numeric, String, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("sku", name="uq_products_sku"),
        CheckConstraint("price >= 0 AND price <> 'NaN'::numeric", name="ck_products_price"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sku: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(2000))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Warehouse(Base):
    __tablename__ = "warehouses"
    __table_args__ = (UniqueConstraint("name", name="uq_warehouses_name"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    location: Mapped[str] = mapped_column(String(200))


class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (
        CheckConstraint("on_hand >= 0", name="ck_inventory_on_hand"),
        CheckConstraint("reserved >= 0 AND reserved <= on_hand", name="ck_inventory_reserved"),
        Index("ix_inventory_warehouse_product", "warehouse_id", "product_id"),
    )

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), primary_key=True)
    on_hand: Mapped[int] = mapped_column(BigInteger, server_default="0")
    reserved: Mapped[int] = mapped_column(BigInteger, server_default="0")

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["product_id", "warehouse_id"], ["inventory.product_id", "inventory.warehouse_id"]
        ),
        CheckConstraint(
            "movement_type = 'RECEIPT' AND delta_on_hand > 0 AND delta_reserved = 0",
            name="ck_movements_receipt",
        ),
        Index("ix_movements_inventory", "product_id", "warehouse_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    product_id: Mapped[int] = mapped_column(BigInteger)
    warehouse_id: Mapped[int] = mapped_column(BigInteger)
    delta_on_hand: Mapped[int] = mapped_column(BigInteger)
    delta_reserved: Mapped[int] = mapped_column(BigInteger)
    movement_type: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
