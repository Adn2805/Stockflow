"""Add orders, price snapshots, and order movements."""

from alembic import op
import sqlalchemy as sa

revision = "0002_orders"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None

MOVEMENT_CHECK = """
    (movement_type = 'RECEIPT' AND order_id IS NULL AND delta_on_hand > 0 AND delta_reserved = 0)
    OR (movement_type = 'RESERVATION' AND order_id IS NOT NULL AND delta_on_hand = 0 AND delta_reserved > 0)
    OR (movement_type = 'CANCELLATION' AND order_id IS NOT NULL AND delta_on_hand = 0 AND delta_reserved < 0)
    OR (movement_type = 'FULFILLMENT' AND order_id IS NOT NULL AND delta_on_hand < 0 AND delta_reserved = delta_on_hand)
"""


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("customer_reference", sa.String(200), nullable=False),
        sa.Column("warehouse_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_orders_idempotency_key"),
        sa.CheckConstraint("status IN ('RESERVED', 'FULFILLED', 'CANCELLED')", name="ck_orders_status"),
        sa.ForeignKeyConstraint(
            ["warehouse_id"], ["warehouses.id"], deferrable=True, initially="DEFERRED"
        ),
    )
    op.create_table(
        "order_items",
        sa.Column("order_id", sa.BigInteger(), sa.ForeignKey("orders.id"), primary_key=True),
        sa.Column("product_id", sa.BigInteger(), sa.ForeignKey("products.id"), primary_key=True),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("unit_price_snapshot", sa.Numeric(12, 2), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_order_items_quantity"),
        sa.CheckConstraint(
            "unit_price_snapshot >= 0 AND unit_price_snapshot <> 'NaN'::numeric",
            name="ck_order_items_price",
        ),
    )
    op.add_column("stock_movements", sa.Column("order_id", sa.BigInteger()))
    op.create_foreign_key(
        "fk_movements_order", "stock_movements", "orders", ["order_id"], ["id"]
    )
    op.create_index(
        "uq_movements_order_product_type", "stock_movements",
        ["order_id", "product_id", "movement_type"], unique=True,
    )
    op.create_check_constraint("ck_movements_type_and_deltas", "stock_movements", MOVEMENT_CHECK)
    op.drop_constraint("ck_movements_receipt", "stock_movements", type_="check")


def downgrade() -> None:
    # The receipt-only constraint blocks downgrade if order history exists.
    op.create_check_constraint(
        "ck_movements_receipt", "stock_movements",
        "movement_type = 'RECEIPT' AND delta_on_hand > 0 AND delta_reserved = 0",
    )
    op.drop_constraint("ck_movements_type_and_deltas", "stock_movements", type_="check")
    op.drop_index("uq_movements_order_product_type", table_name="stock_movements")
    op.drop_constraint("fk_movements_order", "stock_movements", type_="foreignkey")
    op.drop_column("stock_movements", "order_id")
    op.drop_table("order_items")
    op.drop_table("orders")
