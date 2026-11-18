"""Closed-loop workload for the disposable API created by performance.py."""

from collections import Counter
import csv
from itertools import count
import json
import os
from pathlib import Path

from locust import HttpUser, constant, events, task
from locust.stats import StatsCSV

outcomes = Counter()
user_ids = count()


class WarehouseUser(HttpUser):
    wait_time = constant(0.05)

    def on_start(self):
        self.user_id = next(user_ids)
        self.step = self.user_id % 10
        self.client.headers.update({"Authorization": "Bearer " + os.environ["STOCKFLOW_BENCH_TOKEN"]})
        self.client.trust_env = False

    @task
    def warehouse_work(self):
        step = self.step
        self.step += 1
        lane = step % 10
        if lane < 5:
            self.client.get("/products?limit=25", name="/products", timeout=10)
        elif lane < 7:
            self.client.get(
                f"/inventory?warehouse_id={1 + self.user_id % 2}&limit=25",
                name="/inventory", timeout=10,
            )
        else:
            with self.client.post(
                "/orders", name="/orders", timeout=10, catch_response=True,
                headers={"Idempotency-Key": f"load-{self.user_id}-{step}"},
                json={
                    "warehouse_id": 1 + self.user_id % 2, "customer_reference": "synthetic-load",
                    "items": [{"product_id": 1, "quantity": 1 + lane % 2}],
                },
            ) as response:
                if response.status_code == 201:
                    outcomes["accepted_orders"] += 1
                elif response.status_code == 409 and response.json().get("detail") == "Insufficient available stock":
                    outcomes["stock_rejections"] += 1
                    response.success()


@events.test_stop.add_listener
def record_results(environment, **kwargs):
    prefix = Path(os.environ["STOCKFLOW_BENCH_PREFIX"])
    prefix.with_name(prefix.name + "_orders.json").write_text(
        json.dumps(dict(outcomes), indent=2) + "\n", encoding="utf-8"
    )
    final = StatsCSV(environment, [0.50, 0.95, 0.99])
    for suffix, write in (
        ("stats", final.requests_csv), ("failures", final.failures_csv),
        ("exceptions", final.exceptions_csv),
    ):
        with prefix.with_name(f"{prefix.name}_{suffix}.csv").open(
            "w", encoding="utf-8", newline=""
        ) as stream:
            write(csv.writer(stream))
