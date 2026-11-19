"""Run the isolated Locust matrix and retain CSV, SQL plans, and PostgreSQL audits."""

import argparse
import csv
from importlib.metadata import version
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
from time import monotonic, sleep

from sqlalchemy import text

from environment import Benchmark, audit, benchmark, is_consistent, metadata, seed

LOCUSTFILE = Path(__file__).with_name("locustfile.py")
USERS = (10, 25, 50, 100)


def database_activity(db, application_name: str) -> tuple[int, int, int]:
    db.exec_driver_sql("SELECT pg_stat_clear_snapshot()")
    return db.execute(text("""
        SELECT (
            SELECT deadlocks FROM pg_stat_database WHERE datname = current_database()
        ), count(*) FILTER (WHERE wait_event_type = 'Lock'),
           count(*) FILTER (WHERE wait_event_type = 'Lock' AND wait_event = 'transactionid')
        FROM pg_stat_activity WHERE application_name = :application_name
    """), {"application_name": application_name}).one()


def capture_plan(target: Benchmark, path: Path):
    with target.engine.begin() as db:
        plan = db.execute(text("""
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
            SELECT product_id, warehouse_id, on_hand, reserved
            FROM inventory WHERE warehouse_id = 1 AND product_id IN (1, 2)
            ORDER BY product_id FOR UPDATE
        """)).scalar_one()
    path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")


def run_trial(users: int, repeat: int, duration: int, port: int, output: Path, workload: str) -> dict:
    prefix = output / f"u{users}-run{repeat}"
    outcomes_file = prefix.with_name(prefix.name + "_orders.json")
    success_only = workload == "successful-orders"
    opening = 10005 if success_only else 55
    expected_on_hand = (opening - 5) * 2000
    with benchmark(port) as target:
        seed(target.engine, products=1000, warehouses=2, opening=opening, historical_per_balance=5)
        before = audit(target.engine)
        if users == USERS[0] and repeat == 1:
            capture_plan(target, output / "inventory-lock-plan.json")
        env = os.environ | {
            "NO_PROXY": "127.0.0.1",
            "STOCKFLOW_BENCH_TOKEN": target.token,
            "STOCKFLOW_BENCH_PREFIX": str(prefix),
            "STOCKFLOW_BENCH_WORKLOAD": workload,
        }
        command = [
            sys.executable, "-m", "locust", "-f", str(LOCUSTFILE), "--host", target.url,
            "--headless", "-u", str(users), "-r", str(users), "-t", f"{duration}s",
            "--stop-timeout", "12", "--only-summary",
        ]

        with target.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as db:
            initial_deadlocks, _, _ = database_activity(db, target.application_name)
            lock_samples = transaction_lock_samples = peak_blocked = samples = 0
            with prefix.with_suffix(".log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    deadline = monotonic() + duration + 45
                    while process.poll() is None:
                        if monotonic() >= deadline:
                            raise RuntimeError(f"Locust timed out for {prefix.name}")
                        _, blocked, transaction_blocked = database_activity(db, target.application_name)
                        lock_samples += int(blocked > 0)
                        transaction_lock_samples += int(transaction_blocked > 0)
                        peak_blocked = max(peak_blocked, blocked)
                        samples += 1
                        sleep(0.2)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=10)
            final_deadlocks, _, _ = database_activity(db, target.application_name)
        after = audit(target.engine)
        after_stats = metadata(target.engine)
        results_path = prefix.with_name(prefix.name + "_stats.csv")
        with results_path.open(encoding="utf-8", newline="") as stream:
            stats = {row["Name"]: row for row in csv.DictReader(stream)}
        aggregate = stats["Aggregated"]
        outcomes = json.loads(outcomes_file.read_text(encoding="utf-8"))
        accepted = outcomes.get("accepted_orders", 0)
        rejected = outcomes.get("stock_rejections", 0)
        requests = int(aggregate["Request Count"])
        order_requests = requests if success_only else int(stats.get("/orders", {}).get("Request Count", 0))
        successful_orders = stats.get("/orders [201]")
        failures = int(aggregate["Failure Count"])
        deadlocks = final_deadlocks - initial_deadlocks
        return {
            "metadata": after_stats | {"locust": version("locust")},
            "workload": workload,
            "users": users, "repeat": repeat, "duration_seconds": duration, "spawn_rate": users,
            "requests": requests, "order_requests": order_requests,
            "requests_per_second": float(aggregate["Requests/s"]),
            "median_ms": float(aggregate["Median Response Time"]), "p95_ms": float(aggregate["95%"]),
            "p99_ms": float(aggregate["99%"]),
            "success_metrics": {
                "requests_per_second": float(successful_orders["Requests/s"]),
                "p50_ms": float(successful_orders["50%"]),
                "p95_ms": float(successful_orders["95%"]),
                "p99_ms": float(successful_orders["99%"]),
            } if successful_orders else None,
            "unexpected_errors": failures, "unexpected_error_rate": failures / requests if requests else None,
            "accepted_orders": accepted, "stock_rejections": rejected,
            "stock_rejection_rate_of_orders": rejected / order_requests if order_requests else None,
            "deadlocks_database_delta": deadlocks, "database_samples": samples,
            "samples_with_lock_wait": lock_samples, "samples_with_transaction_lock_wait": transaction_lock_samples,
            "peak_lock_waiting_api_connections": peak_blocked,
            "before": before, "after": after, "locust_exit_code": process.returncode,
            "passed": (
                process.returncode == 0 and requests > 0 and accepted > 0 and failures == 0 and deadlocks == 0
                and accepted + rejected == order_requests
                and (not success_only or (rejected == 0 and successful_orders is not None
                     and int(successful_orders["Request Count"]) == accepted == order_requests
                     and after["reserved"] - before["reserved"] == accepted))
                and is_consistent(before) and is_consistent(after)
                and before["products"] == 1000 and before["warehouses"] == 2 and before["orders"] == 10000
                and after["on_hand"] == before["on_hand"] == expected_on_hand and before["reserved"] == 0
                and after["orders"] == before["orders"] + accepted
                and after["reserved_orders"] == accepted
                and after["order_items"] == before["order_items"] + accepted
                and after["movements"] == before["movements"] + accepted
            ),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=58083)
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--workload", choices=("mixed", "successful-orders"), default="mixed")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.seconds < 2 or args.repeats < 1:
        parser.error("Run for at least two seconds and one repeat")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    trials = []
    metrics = ("requests_per_second", "median_ms", "p95_ms", "p99_ms", "unexpected_error_rate",
               "stock_rejection_rate_of_orders")
    for users in USERS:
        for repeat in range(1, args.repeats + 1):
            trial = run_trial(users, repeat, args.seconds, args.port, output, args.workload)
            trials.append(trial)
            (output / "trials.json").write_text(json.dumps(trials, indent=2) + "\n", encoding="utf-8")
            print(f'{users} users run {repeat}: {trial["requests"]} requests, passed={trial["passed"]}', flush=True)
    medians = {
        users: {
            metric: statistics.median(
                trial[metric] for trial in trials if trial["users"] == users and trial[metric] is not None
            ) if any(trial["users"] == users and trial[metric] is not None for trial in trials) else None
            for metric in metrics
        } for users in USERS
    }
    if args.workload == "successful-orders":
        for users, summary in medians.items():
            successful = [trial["success_metrics"] for trial in trials
                          if trial["users"] == users and trial["passed"]]
            summary["successful_orders"] = {
                metric: statistics.median(run[metric] for run in successful)
                for metric in ("requests_per_second", "p50_ms", "p95_ms", "p99_ms")
            } if successful else None
    (output / "medians.json").write_text(json.dumps(medians, indent=2) + "\n", encoding="utf-8")
    if not all(trial["passed"] for trial in trials):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
