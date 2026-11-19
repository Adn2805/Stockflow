"""Export the synthetic dashboard fixture from an isolated local PostgreSQL schema."""

import json
from pathlib import Path
import sys

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
from environment import benchmark
from app.seed_demo import seed

PATHS = (
    "/products", "/warehouses", "/inventory", "/orders",
    "/reports/stock-movements", "/reports/reconciliation",
)


def main():
    with benchmark(58084) as target:
        with Session(target.engine) as session:
            seed(session)
        with target.engine.begin() as connection:
            for table in ("products", "orders", "stock_movements"):
                connection.exec_driver_sql(
                    f"UPDATE {table} SET created_at = TIMESTAMPTZ '2026-10-01 10:00:00+00' + id * interval '5 minutes'"
                )
        with httpx.Client(base_url=target.url, trust_env=False,
                          headers={"Authorization": f"Bearer {target.token}"}) as client:
            snapshot = {}
            for path in PATHS:
                response = client.get(path, params={"limit": 100})
                response.raise_for_status()
                snapshot[path] = response.json()
    if len(snapshot["/products"]) != 5 or len(snapshot["/orders"]) != 4 or snapshot["/reports/reconciliation"]:
        raise RuntimeError("Synthetic snapshot failed verification")
    (ROOT / "frontend/src/demo-snapshot.json").write_text(
        json.dumps(snapshot, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
