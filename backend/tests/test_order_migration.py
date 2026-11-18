from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text


def test_upgrade_preserves_existing_phase_one_receipts(database):
    with database.connect() as connection:
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.attributes["connection"] = connection
        command.downgrade(config, "0001_foundation")

        with connection.begin():
            connection.execute(text("INSERT INTO products (sku, name, price) VALUES ('P1', 'Gloves', 1.25)"))
            connection.execute(text("INSERT INTO warehouses (name, location) VALUES ('Central', 'Test site')"))
            connection.execute(text("INSERT INTO inventory (product_id, warehouse_id, on_hand) VALUES (1, 1, 7)"))
            connection.execute(text("""
                INSERT INTO stock_movements
                    (product_id, warehouse_id, delta_on_hand, delta_reserved, movement_type)
                VALUES (1, 1, 7, 0, 'RECEIPT')
            """))

        command.upgrade(config, "head")
        assert connection.execute(text("SELECT on_hand, reserved FROM inventory")).one() == (7, 0)
        assert connection.execute(text("""
            SELECT delta_on_hand, delta_reserved, movement_type, order_id FROM stock_movements
        """)).one() == (7, 0, "RECEIPT", None)
        assert connection.scalar(text("SELECT count(*) FROM orders")) == 0
        connection.rollback()
        command.check(config)
