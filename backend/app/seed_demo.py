"""Seed an empty, dedicated StockFlow demo database with synthetic records."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from random import Random

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

EXTRA_CATALOG = (
    ("Packing Tape", "3.75"), ("Thermal Label Roll", "9.90"),
    ("Corrugated Shipping Box", "2.40"), ("Stretch Wrap Roll", "14.80"),
    ("Pallet Corner Protector", "1.25"), ("Reusable Picking Tote", "18.50"),
    ("Barcode Scanner Stand", "24.00"), ("Floor Marking Tape", "11.25"),
    ("Insulated Shipping Liner", "5.60"), ("Anti-Static Pouch", "0.85"),
    ("Ratchet Tie-Down", "13.75"), ("Absorbent Spill Pad", "4.25"),
    ("Padded Mailer", "1.90"), ("Tamper-Evident Seal", "0.70"),
    ("Document Pouch", "0.45"),
)
EXPANDED_ORDERS = 320
SNAPSHOT_START = datetime(2026, 10, 1, 10, tzinfo=UTC)


def seed(session: Session, *, expanded: bool = False) -> None:
    with session.begin():
        for model in (Product, Warehouse, Inventory, Order, StockMovement, User):
            if session.scalar(select(exists(select(model)))):
                raise ValueError("Demo seeding requires a fresh, empty database")
        warehouses = [
            Warehouse(name="Central warehouse", location="Synthetic distribution site"),
            Warehouse(name="North warehouse", location="Synthetic satellite site"),
        ]
        if expanded:
            warehouses.extend([
                Warehouse(name="West fulfillment center", location="Synthetic fulfillment site"),
                Warehouse(name="South distribution hub", location="Synthetic distribution site"),
            ])
        catalog = CATALOG
        if expanded:
            catalog = tuple((sku, name, description, price, openings + (90, 60))
                            for sku, name, description, price, openings in catalog)
            catalog += tuple(
                (f"SF-SUP-{index:02}", name, None, price,
                 (105 + index * 7, 65 + index * 4, 85 + index * 6, 75 + index * 5))
                for index, (name, price) in enumerate(EXTRA_CATALOG, 1)
            )
        products = [
            Product(sku=sku, name=name, description=description, price=price)
            for sku, name, description, price, _ in catalog
        ]
        session.add_all(warehouses + products)
        session.flush()

        balances = {}
        for product, (_, _, _, _, openings) in zip(products, catalog, strict=True):
            for warehouse, quantity in zip(warehouses, openings, strict=True):
                key = (product.id, warehouse.id)
                balance = Inventory(product_id=key[0], warehouse_id=key[1], on_hand=quantity, reserved=0)
                balances[key] = balance
        session.add_all(balances.values())
        session.flush()

        def movement(balance, kind, on_hand, reserved, when, order_id=None):
            session.add(StockMovement(
                product_id=balance.product_id, warehouse_id=balance.warehouse_id,
                order_id=order_id, movement_type=kind, delta_on_hand=on_hand, delta_reserved=reserved,
                created_at=when,
            ))

        for balance in balances.values():
            movement(balance, "RECEIPT", balance.on_hand, 0, SNAPSHOT_START)

        orders = [
            ("FULFILLED", 0, ((0, 8), (2, 3))),
            ("CANCELLED", 1, ((3, 2),)),
            ("RESERVED", 0, ((0, 5), (1, 3))),
            ("RESERVED", 1, ((2, 2), (4, 1))),
        ]
        if expanded:
            rng = Random(46)
            extra_indices = range(len(CATALOG), len(products))
            for index in range(len(orders) + 1, EXPANDED_ORDERS + 1):
                status = "RESERVED" if index > 285 else "CANCELLED" if index % 8 == 0 else "FULFILLED"
                lines = tuple((product, rng.randint(1, 9))
                              for product in rng.sample(extra_indices, rng.choices((1, 2, 3), (3, 5, 2))[0]))
                orders.append((status, rng.randrange(len(warehouses)), lines))
        for index, (status, site, lines) in enumerate(orders, start=1):
            warehouse = warehouses[site]
            when = SNAPSHOT_START + (timedelta(days=(index - 1) // 12, minutes=35 * ((index - 1) % 12) + 5)
                                     if expanded else timedelta(minutes=5 * index))
            reference = f"Demo customer {index:03}" if index > 4 else f"Demo customer {index:02}"
            order = Order(
                customer_reference=reference, warehouse_id=warehouse.id,
                status=status, idempotency_key=f"synthetic-seed-{index}",
                request_hash=sha256(reference.encode()).hexdigest(),
                created_at=when,
                items=[OrderItem(product_id=products[p].id, quantity=q, unit_price_snapshot=products[p].price)
                       for p, q in lines],
            )
            session.add(order)
            session.flush()
            if expanded and index % 9 == 0:
                balance = balances[(order.items[0].product_id, warehouse.id)]
                quantity = 24 + index % 48
                balance.on_hand += quantity
                movement(balance, "RECEIPT", quantity, 0, when - timedelta(minutes=2))
            for line in order.items:
                balance = balances[(line.product_id, warehouse.id)]
                if expanded and index > 4 and balance.on_hand - balance.reserved < line.quantity + 12:
                    balance.on_hand += 120
                    movement(balance, "RECEIPT", 120, 0, when - timedelta(minutes=1))
            for line in order.items:
                balance = balances[(line.product_id, warehouse.id)]
                movement(balance, "RESERVATION", 0, line.quantity, when, order.id)
            for line in order.items:
                balance = balances[(line.product_id, warehouse.id)]
                if status == "FULFILLED":
                    balance.on_hand -= line.quantity
                    movement(balance, "FULFILLMENT", -line.quantity, -line.quantity, when + timedelta(minutes=10), order.id)
                elif status == "CANCELLED":
                    movement(balance, "CANCELLATION", 0, -line.quantity, when + timedelta(minutes=10), order.id)
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
