"""Prepare and remove an isolated PostgreSQL schema for browser tests."""

import os
import re
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app.auth import User, password_hasher
from app.seed_demo import seed
from app.models import Inventory, Product, StockMovement, Warehouse


def main():
    action, schema = sys.argv[1:]
    url = make_url(os.environ["TEST_DATABASE_URL"])
    if (
        url.drivername != "postgresql+psycopg"
        or not (url.database or "").endswith("_test")
        or not re.fullmatch(r"stockflow_e2e_[a-f0-9]{32}", schema)
    ):
        raise ValueError("Browser tests require a dedicated PostgreSQL test database and schema")

    admin = create_engine(url)
    try:
        if action == "cleanup":
            with admin.begin() as db:
                db.execute(DropSchema(schema, if_exists=True, cascade=True))
            return
        if action != "prepare":
            raise ValueError("Unknown browser database action")
        with admin.begin() as db:
            db.execute(CreateSchema(schema))
        engine = create_engine(url.update_query_dict({"options": f"-csearch_path={schema}"}))
        try:
            with engine.connect() as db:
                config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
                config.attributes["connection"] = db
                command.upgrade(config, "head")
            if os.getenv("PUBLIC_DEMO") == "true":
                with Session(engine) as db:
                    seed(db)
                return
            with Session(engine) as db, db.begin():
                password_hash = password_hasher.hash(os.environ["STOCKFLOW_E2E_PASSWORD"])
                db.add_all([User(username=role, role=role, password_hash=password_hash)
                            for role in ("admin", "guest")])
                product = Product(sku="E2E-GLOVE", name="Work gloves", price="12.50")
                warehouse = Warehouse(name="Central warehouse", location="Test site")
                db.add_all([product, warehouse])
                db.flush()
                key = {"product_id": product.id, "warehouse_id": warehouse.id}
                db.add(Inventory(**key, on_hand=6))
                db.flush()
                db.add(StockMovement(**key, movement_type="RECEIPT", delta_on_hand=6, delta_reserved=0))
        finally:
            engine.dispose()
    finally:
        admin.dispose()


if __name__ == "__main__":
    main()
