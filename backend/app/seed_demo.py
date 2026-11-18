"""Seed an empty, dedicated StockFlow demo database with synthetic records."""

from hashlib import sha256

from sqlalchemy import create_engine, exists, select
from sqlalchemy.orm import Session

from app.auth import User
from app.core.config import Settings
from app.models import Inventory, Order, OrderItem, Product, StockMovement, Warehouse

CATALOG = (
    ("SF-GLV-01", "Grip Work Gloves", "Textured palm with a breathable liner.", "12.50", (50, 24)),
    ("SF-BOOT-02", "Steel-Toe Work Boots", "Reinforced toe and slip-resistant sole.", "79.00", (17, 9)),
    ("SF-VEST-03", "Reflective Safety Vest", "High-visibility mesh with adjustable fit.", "17.95", (31, 4)),
    ("SF-GOG-04", "Clear Safety Goggles", "Wraparound eye protection for workshop use.", "8.75", (12, 3)),
    ("SF-KIT-05", "Warehouse First Aid Kit", "Compact kit for a warehouse station.", "34.00", (8, 2)),
)


def seed(session: Session) -> None:
    with session.begin():
        for model in (Product, Warehouse, Inventory, Order, StockMovement, User):
            if session.scalar(select(exists(select(model)))):
                raise ValueError("Demo seeding requires a fresh, empty database")
        warehouses = [
            Warehouse(name="Central warehouse", location="Synthetic distribution site"),
            Warehouse(name="North warehouse", location="Synthetic satellite site"),
        ]
        products = [
            Product(sku=sku, name=name, description=description, price=price)
            for sku, name, description, price, _ in CATALOG
        ]
        session.add_all(warehouses + products)
        session.flush()

        balances = {}
        for product, (_, _, _, _, openings) in zip(products, CATALOG, strict=True):
            for warehouse, quantity in zip(warehouses, openings, strict=True):
                key = (product.id, warehouse.id)
                balance = Inventory(product_id=key[0], warehouse_id=key[1], on_hand=quantity, reserved=0)
                balances[key] = balance
        session.add_all(balances.values())
        session.flush()

        def movement(balance, kind, on_hand, reserved, order_id=None):
            session.add(StockMovement(
                product_id=balance.product_id, warehouse_id=balance.warehouse_id,
                order_id=order_id, movement_type=kind, delta_on_hand=on_hand, delta_reserved=reserved,
            ))

        for balance in balances.values():
            movement(balance, "RECEIPT", balance.on_hand, 0)

        for index, (status, site, lines) in enumerate((
            ("FULFILLED", 0, ((0, 8), (2, 3))),
            ("CANCELLED", 1, ((3, 2),)),
            ("RESERVED", 0, ((0, 5), (1, 3))),
            ("RESERVED", 1, ((2, 2), (4, 1))),
        ), start=1):
            warehouse = warehouses[site]
            reference = f"Demo customer {index:02}"
            order = Order(
                customer_reference=reference, warehouse_id=warehouse.id,
                status=status, idempotency_key=f"synthetic-seed-{index}",
                request_hash=sha256(reference.encode()).hexdigest(),
                items=[OrderItem(product_id=products[p].id, quantity=q, unit_price_snapshot=products[p].price)
                       for p, q in lines],
            )
            session.add(order)
            session.flush()
            for line in order.items:
                balance = balances[(line.product_id, warehouse.id)]
                movement(balance, "RESERVATION", 0, line.quantity, order.id)
                if status == "FULFILLED":
                    balance.on_hand -= line.quantity
                    movement(balance, "FULFILLMENT", -line.quantity, -line.quantity, order.id)
                elif status == "CANCELLED":
                    movement(balance, "CANCELLATION", 0, -line.quantity, order.id)
                else:
                    balance.reserved += line.quantity


def main() -> None:
    settings = Settings()
    engine = create_engine(settings.database_url.get_secret_value(), hide_parameters=True)
    try:
        with Session(engine) as session:
            seed(session)
    finally:
        engine.dispose()
    print("Seeded synthetic catalog, inventory, orders, and stock ledger.")


if __name__ == "__main__":
    main()
