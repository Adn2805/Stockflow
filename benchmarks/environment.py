"""Create a disposable benchmark schema and a loopback-only API."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import os
from pathlib import Path
import platform
from secrets import token_hex
import socket
import subprocess
import sys
from time import monotonic, sleep
from uuid import uuid4

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.schema import CreateSchema, DropSchema

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


@dataclass(frozen=True)
class Benchmark:
    engine: Engine
    url: str
    token: str
    application_name: str


@contextmanager
def benchmark(port: int):
    url = make_url(os.environ["TEST_DATABASE_URL"])
    if (
        url.drivername != "postgresql+psycopg"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not (url.database or "").endswith("_test")
        or "host" in url.query
        or "hostaddr" in url.query
        or "service" in url.query
        or any(os.getenv(var) for var in ("PGHOSTADDR", "PGSERVICE"))
    ):
        raise ValueError("Use a loopback PostgreSQL psycopg URL and a database ending in _test")

    schema = f"stockflow_bench_{uuid4().hex}"
    admin = create_engine(url, hide_parameters=True)
    scoped = url.update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(scoped, hide_parameters=True)
    token = token_hex(32)
    api_url = f"http://127.0.0.1:{port}"
    process = None
    try:
        with admin.begin() as connection:
            connection.execute(CreateSchema(schema))
        with engine.connect() as connection:
            config = Config(str(BACKEND / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        env = os.environ | {
            "DATABASE_URL": scoped.update_query_dict(
                {"application_name": schema}
            ).render_as_string(hide_password=False),
            "WRITE_TOKEN": token,
        }
        with httpx.Client(timeout=1, trust_env=False) as client:
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", port))
                except OSError as exc:
                    raise RuntimeError(f"Cannot bind loopback port {port}") from exc
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                 "--port", str(port), "--backlog", "2048", "--no-access-log"],
                cwd=BACKEND, env=env,
            )
            deadline = monotonic() + 20
            while monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Benchmark API exited with status {process.returncode}")
                try:
                    response = client.get(api_url + "/health")
                    if response.is_success:
                        break
                except httpx.TransportError:
                    pass
                sleep(0.1)
            else:
                raise RuntimeError("Benchmark API did not become ready")

        yield Benchmark(engine, api_url, token, schema)
    finally:
        try:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        finally:
            engine.dispose()
            try:
                with admin.begin() as connection:
                    connection.execute(DropSchema(schema, if_exists=True, cascade=True))
            finally:
                admin.dispose()


def metadata(engine: Engine) -> dict:
    with engine.connect() as db:
        postgres = db.scalar(text("SELECT version()"))
    return {
        "started_at_utc": datetime.now(UTC).isoformat(),
        "application_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "application_has_uncommitted_changes": bool(subprocess.check_output(
            ["git", "status", "--porcelain", "--", "backend/app"], cwd=ROOT, text=True
        ).strip()),
        "os": platform.platform(),
        "logical_cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "postgres": postgres,
    }


def seed(engine: Engine, products: int, warehouses: int, opening: int, historical_per_balance: int = 0):
    """Set up deterministic products, receipts and fulfilled single-unit orders in one transaction."""
    with engine.begin() as db:
        db.execute(text("""
            INSERT INTO products (id, sku, name, price)
            SELECT id, 'BENCH-' || id, 'Benchmark product ' || id, 12.50
            FROM generate_series(1, :products) AS id
        """), {"products": products})
        db.execute(text("""
            INSERT INTO warehouses (id, name, location)
            SELECT id, 'Benchmark warehouse ' || id, 'Synthetic dataset'
            FROM generate_series(1, :warehouses) AS id
        """), {"warehouses": warehouses})
        db.execute(text("""
            INSERT INTO inventory (product_id, warehouse_id, on_hand)
            SELECT p.id, w.id, :opening FROM products p CROSS JOIN warehouses w
        """), {"opening": opening})
        db.execute(text("""
            INSERT INTO stock_movements
                (product_id, warehouse_id, movement_type, delta_on_hand, delta_reserved)
            SELECT product_id, warehouse_id, 'RECEIPT', on_hand, 0 FROM inventory
        """))
        if historical_per_balance:
            db.execute(text("""
                CREATE TEMP TABLE historical ON COMMIT DROP AS
                SELECT row_number() OVER (ORDER BY warehouse_id, product_id, copy) AS id,
                    product_id, warehouse_id
                FROM inventory CROSS JOIN generate_series(1, :copies) AS copy
            """), {"copies": historical_per_balance})
            db.execute(text("""
                INSERT INTO orders (id, customer_reference, warehouse_id, status, idempotency_key, request_hash)
                SELECT id, 'synthetic-history', warehouse_id, 'FULFILLED', 'historical-' || id, :hash
                FROM historical ORDER BY id
            """), {"hash": sha256(b"synthetic-history").hexdigest()})
            db.execute(text("""
                INSERT INTO order_items (order_id, product_id, quantity, unit_price_snapshot)
                SELECT id, product_id, 1, 12.50 FROM historical
            """))
            db.execute(text("""
                INSERT INTO stock_movements
                    (product_id, warehouse_id, order_id, movement_type, delta_on_hand, delta_reserved)
                SELECT product_id, warehouse_id, id, 'RESERVATION', 0, 1 FROM historical
                UNION ALL
                SELECT product_id, warehouse_id, id, 'FULFILLMENT', -1, -1 FROM historical
            """))
            db.execute(text("UPDATE inventory SET on_hand = on_hand - :copies"), {"copies": historical_per_balance})
        for table in ("products", "warehouses", "orders"):
            db.exec_driver_sql(f"""
                SELECT setval(pg_get_serial_sequence('{table}', 'id'),
                              COALESCE(max(id), 1), max(id) IS NOT NULL)
                FROM {table}
            """)
        db.exec_driver_sql("ANALYZE products, warehouses, inventory, orders, order_items, stock_movements")


def audit(engine: Engine) -> dict:
    with engine.connect() as db:
        result = dict(db.execute(text("""
            WITH ledger AS (
                SELECT product_id, warehouse_id, sum(delta_on_hand) AS on_hand, sum(delta_reserved) AS reserved
                FROM stock_movements GROUP BY product_id, warehouse_id
            ), open_orders AS (
                SELECT oi.product_id, o.warehouse_id, sum(oi.quantity) AS reserved
                FROM order_items oi JOIN orders o ON o.id = oi.order_id
                WHERE o.status = 'RESERVED' GROUP BY oi.product_id, o.warehouse_id
            ), movements_by_line AS (
                SELECT order_id, product_id,
                    sum(delta_on_hand) AS on_hand, sum(delta_reserved) AS reserved,
                    count(*) FILTER (WHERE movement_type = 'RESERVATION') AS reservations,
                    count(*) FILTER (WHERE movement_type = 'CANCELLATION') AS cancellations,
                    count(*) FILTER (WHERE movement_type = 'FULFILLMENT') AS fulfillments,
                    min(warehouse_id) AS first_warehouse, max(warehouse_id) AS last_warehouse
                FROM stock_movements WHERE order_id IS NOT NULL GROUP BY order_id, product_id
            )
            SELECT
                (SELECT count(*) FROM products) AS products,
                (SELECT count(*) FROM warehouses) AS warehouses,
                (SELECT count(*) FROM orders) AS orders,
                (SELECT count(*) FROM order_items) AS order_items,
                (SELECT count(*) FROM stock_movements) AS movements,
                (SELECT count(*) FROM orders WHERE status = 'RESERVED') AS reserved_orders,
                (SELECT count(*) - count(DISTINCT idempotency_key) FROM orders) AS duplicate_keys,
                (SELECT count(*) FROM orders o WHERE NOT EXISTS
                    (SELECT 1 FROM order_items oi WHERE oi.order_id = o.id)) AS empty_orders,
                (SELECT coalesce(sum(on_hand), 0) FROM inventory) AS on_hand,
                (SELECT coalesce(sum(reserved), 0) FROM inventory) AS reserved,
                (SELECT count(*) FROM inventory WHERE reserved < 0 OR on_hand < reserved) AS invalid_balances,
                (SELECT count(*) FROM inventory i FULL JOIN ledger l USING (product_id, warehouse_id)
                    WHERE i.on_hand IS DISTINCT FROM coalesce(l.on_hand, 0)
                       OR i.reserved IS DISTINCT FROM coalesce(l.reserved, 0)) AS ledger_discrepancies,
                (SELECT count(*) FROM inventory i FULL JOIN open_orders o USING (product_id, warehouse_id)
                    WHERE i.reserved IS DISTINCT FROM coalesce(o.reserved, 0)) AS reservation_discrepancies,
                (SELECT count(*) FROM order_items oi FULL JOIN movements_by_line m USING (order_id, product_id)
                    JOIN orders o ON o.id = coalesce(oi.order_id, m.order_id)
                    WHERE oi.order_id IS NULL OR m.order_id IS NULL
                       OR m.first_warehouse <> o.warehouse_id OR m.last_warehouse <> o.warehouse_id
                       OR m.reservations <> 1 OR m.cancellations <> (o.status = 'CANCELLED')::int
                       OR m.fulfillments <> (o.status = 'FULFILLED')::int
                       OR m.on_hand <> CASE WHEN o.status = 'FULFILLED' THEN -oi.quantity ELSE 0 END
                       OR m.reserved <> CASE WHEN o.status = 'RESERVED' THEN oi.quantity ELSE 0 END)
                    AS invalid_order_movements
        """)).mappings().one())
    return {key: int(value) for key, value in result.items()}


def is_consistent(snapshot: dict) -> bool:
    return not any(snapshot[key] for key in (
        "duplicate_keys", "empty_orders", "invalid_balances", "ledger_discrepancies",
        "reservation_discrepancies", "invalid_order_movements",
    ))
