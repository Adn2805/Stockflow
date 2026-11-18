from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint,
    Identity, Index, Numeric, String, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_orders_idempotency_key"),
        CheckConstraint("status IN ('RESERVED', 'FULFILLED', 'CANCELLED')", name="ck_orders_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    customer_reference: Mapped[str] = mapped_column(String(200))
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", deferrable=True, initially="DEFERRED")
    )
    status: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    items: Mapped[list["OrderItem"]] = relationship(lazy="selectin", order_by="OrderItem.product_id")


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_items_quantity"),
        CheckConstraint(
            "unit_price_snapshot >= 0 AND unit_price_snapshot <> 'NaN'::numeric",
            name="ck_order_items_price",
        ),
    )

    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    quantity: Mapped[int] = mapped_column(BigInteger)
    unit_price_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["product_id", "warehouse_id"], ["inventory.product_id", "inventory.warehouse_id"]
        ),
        CheckConstraint(
            """
            (movement_type = 'RECEIPT' AND order_id IS NULL AND delta_on_hand > 0 AND delta_reserved = 0)
            OR (movement_type = 'RESERVATION' AND order_id IS NOT NULL AND delta_on_hand = 0 AND delta_reserved > 0)
            OR (movement_type = 'CANCELLATION' AND order_id IS NOT NULL AND delta_on_hand = 0 AND delta_reserved < 0)
            OR (movement_type = 'FULFILLMENT' AND order_id IS NOT NULL AND delta_on_hand < 0 AND delta_reserved = delta_on_hand)
            """,
            name="ck_movements_type_and_deltas",
        ),
        Index("ix_movements_inventory", "product_id", "warehouse_id", "id"),
        Index("uq_movements_order_product_type", "order_id", "product_id", "movement_type", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    product_id: Mapped[int] = mapped_column(BigInteger)
    warehouse_id: Mapped[int] = mapped_column(BigInteger)
    delta_on_hand: Mapped[int] = mapped_column(BigInteger)
    delta_reserved: Mapped[int] = mapped_column(BigInteger)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", name="fk_movements_order"))
    movement_type: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
