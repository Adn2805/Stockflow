"""Export the synthetic dashboard fixture from an isolated local PostgreSQL schema."""

import json
from pathlib import Path
import sys

import httpx
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
from environment import benchmark
from app.seed_demo import EXPANDED_ORDERS, seed

PATHS = (
    "/products", "/warehouses", "/inventory", "/orders",
    "/reports/stock-movements", "/reports/reconciliation",
)


def main():
    with benchmark(58084) as target:
        with Session(target.engine) as session:
            seed(session, expanded=True)
        with httpx.Client(base_url=target.url, trust_env=False,
                          headers={"Authorization": f"Bearer {target.token}"}) as client:
            snapshot = {}
            for path in PATHS:
                rows = []
                while True:
                    response = client.get(path, params={"limit": 100, "offset": len(rows)})
                    response.raise_for_status()
                    page = response.json()
                    rows.extend(page)
                    if len(page) < 100:
                        break
                snapshot[path] = rows
    orders = snapshot["/orders"]
    movements = snapshot["/reports/stock-movements"]
    if (len(orders) != EXPANDED_ORDERS
            or {row["status"] for row in orders} != {"FULFILLED", "CANCELLED", "RESERVED"}
            or len(movements) <= 1000
            or snapshot["/reports/reconciliation"]):
        raise RuntimeError("Synthetic snapshot failed verification")
    sections = []
    for path, rows in snapshot.items():
        records = ",\n".join("    " + json.dumps(row, separators=(",", ":")) for row in rows)
        sections.append(f"  {json.dumps(path)}: [\n{records}\n  ]" if rows else f"  {json.dumps(path)}: []")
    (ROOT / "frontend/src/demo-snapshot.json").write_text(
        "{\n" + ",\n".join(sections) + "\n}\n", encoding="utf-8"
    )
    print(f"Exported {len(orders)} orders and {len(movements)} stock movements with zero discrepancies.")


if __name__ == "__main__":
    main()
