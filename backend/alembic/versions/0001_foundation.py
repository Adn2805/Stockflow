"""Create the product, warehouse, inventory and receipt movement tables."""

from alembic import op
import sqlalchemy as sa

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(2000)),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("sku", name="uq_products_sku"),
        sa.CheckConstraint("price >= 0 AND price <> 'NaN'::numeric", name="ck_products_price"),
    )
    op.create_table(
        "warehouses",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("location", sa.String(200), nullable=False),
        sa.UniqueConstraint("name", name="uq_warehouses_name"),
    )
    op.create_table(
        "inventory",
        sa.Column("product_id", sa.BigInteger(), sa.ForeignKey("products.id"), primary_key=True),
        sa.Column("warehouse_id", sa.BigInteger(), sa.ForeignKey("warehouses.id"), primary_key=True),
        sa.Column("on_hand", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("reserved", sa.BigInteger(), server_default="0", nullable=False),
        sa.CheckConstraint("on_hand >= 0", name="ck_inventory_on_hand"),
        sa.CheckConstraint("reserved >= 0 AND reserved <= on_hand", name="ck_inventory_reserved"),
    )
    op.create_index("ix_inventory_warehouse_product", "inventory", ["warehouse_id", "product_id"])
    op.create_table(
        "stock_movements",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("warehouse_id", sa.BigInteger(), nullable=False),
        sa.Column("delta_on_hand", sa.BigInteger(), nullable=False),
        sa.Column("delta_reserved", sa.BigInteger(), nullable=False),
        sa.Column("movement_type", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id", "warehouse_id"], ["inventory.product_id", "inventory.warehouse_id"]
        ),
        sa.CheckConstraint(
            "movement_type = 'RECEIPT' AND delta_on_hand > 0 AND delta_reserved = 0",
            name="ck_movements_receipt",
        ),
    )
    op.create_index("ix_movements_inventory", "stock_movements", ["product_id", "warehouse_id", "id"])


def downgrade() -> None:
    op.drop_table("stock_movements")
    op.drop_table("inventory")
    op.drop_table("warehouses")
    op.drop_table("products")
