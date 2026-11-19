# StockFlow resume benchmark

## Reproduce

From the repository root, use Python 3.12, install `benchmarks/requirements.txt`, and export `TEST_DATABASE_URL` for a loopback PostgreSQL database ending in `_test`. Run the benchmarks serially and keep other local workloads idle where possible.

```sh
python -m pip install -r benchmarks/requirements.txt
python benchmarks/concurrency.py --output benchmarks/local-results/resume-2027/concurrency.json
python benchmarks/performance.py --workload successful-orders --seconds 12 --repeats 3 --output benchmarks/local-results/resume-2027/locust
```

Each trial uses a fresh Alembic-migrated schema and a single Uvicorn process on loopback. The harness removes only its own temporary schema. The load generator, API, and PostgreSQL share the host. The checked application revision was `abfcd38dc59064062c887eb4a5e9535d7620e52f` with a clean `backend/app`. The harness scripts were run from the working tree. Host and package metadata are in the trial records.

The Locust workload uses 10, 25, 50, and 100 closed-loop users with three independent 12-second trials at each load. The spawn rate equals the target user count per second. Each user waits 50 ms between requests and places one-unit orders over a rotating pool of 1,000 products and two warehouses, using a unique idempotency key for each order. Every trial starts with 10,000 fulfilled historical orders, 22,000 ledger rows, and 20 million on-hand units spread across 2,000 balances. Reorder policies are absent and no Telegram worker runs. Throughput and latency include ramp-up and in-flight completion. Percentiles are Locust histogram estimates. The report uses medians of the three per-trial measurements, while the per-trial CSVs retain the underlying Locust statistics.

The harness records successful HTTP 201 orders in their own statistics row. An insufficient-stock HTTP 409 is classified separately and fails the successful-order trial. Any other response is unexpected. Audits verify exact order, line, reservation, and ledger deltas, unchanged on-hand stock, and zero consistency violations. Database lock sampling runs every 200 ms and can miss short waits. The database-wide deadlock counter can include concurrent sessions using the same test database.

The scope is a short, local, single-process synthetic workload. The 500-order burst measures synchronized client attempts. Database transaction admission is controlled independently by the API and PostgreSQL. The capacity of a production deployment and the latency of a sustained, skewed or Telegram-enabled workload are outside these measurements. The [Phase 4 results](README.md) measured a different, rejection-heavy workload and do not constitute a before/after comparison.

## Index and transaction review

The order service locks inventory rows in product ID order using `SELECT ... FOR UPDATE` and a warehouse/product filter. On the seeded fixture, PostgreSQL used `ix_inventory_warehouse_product` to lock both rows in **0.077 ms** execution time, with 12 shared-buffer hits and zero reads. This is one uncontended SQL plan, with end-to-end latency measured separately by Locust. The order insert claims idempotency through `uq_orders_idempotency_key`, and stock movements have a unique constraint index for order, product, and movement type. Replenishment and the outbox also use purpose-built partial indexes.

The review revealed no justified index change for this workload. Existing indexes cover the checked lookup and uniqueness contracts. Row locks and transaction boundaries protect order correctness. No optimization was applied and no p95 improvement is reported. [Raw inventory lock plan](results/resume-2027/locust/inventory-lock-plan.json)

## Environment

Windows 11 build 26300, Intel Core i5-1235U, 12 logical CPUs, 15.68 GiB RAM. PostgreSQL 17.12 ran in the local Docker container. The host ran Python 3.12.13, FastAPI 0.164.0, SQLAlchemy 2.0.58, psycopg 3.3.9, Uvicorn 0.54.0, HTTPX 0.28.1, and Locust 2.47.0. Node.js 24.16.0 and the installed Microsoft Edge channel ran frontend verification.

## Results measured on 19 November 2026

| Concurrency case | Attempts | Created (201) | Insufficient stock (409) | Replayed (200) | Burst wall time |
| --- | ---: | ---: | ---: | ---: | ---: |
| One SKU, run 1 | 500 | 100 | 400 | 0 | 5.6526 s |
| One SKU, run 2 | 500 | 100 | 400 | 0 | 5.2528 s |
| Two products, opposite input order | 32 | 5 | 27 | 0 | 0.4756 s |
| Identical shared-key requests | 32 | 1 | 0 | 31 | 0.3633 s |

Each 500-attempt run started with 100 units and finished with 100 on hand, 100 reserved, and zero available. Exactly 100 order headers, 100 lines, and 100 reservation ledger entries committed per run. There were zero units oversold. The two-product scenario reserved 15 units across both products and all successful shared-key responses referred to one order. All four trials recorded zero duplicate keys, empty orders, invalid balances, ledger or reservation discrepancies, and invalid order movements. [Raw concurrency audits](results/resume-2027/concurrency.json)

| Locust users | Successful orders across 3 trials | Median successful orders/s | Median p50 | Median p95 | Median p99 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 2,383 | 68.06 | 82 ms | 160 ms | 210 ms |
| 25 | 2,095 | 62.37 | 340 ms | 580 ms | 680 ms |
| 50 | 1,761 | 48.99 | 920 ms | 1,300 ms | 1,800 ms |
| 100 | 1,880 | 44.30 | 2,100 ms | 3,300 ms | 4,800 ms |

All 12 trials passed with **8,119 HTTP 201 reservations**, zero insufficient-stock responses, zero unexpected errors, and zero increase in the deadlock counter. No lock waits were observed in 787 samples. At 100 users, p95 ranged from 2,100 to 3,900 ms and throughput from 43.03 to 63.08 successful orders/s. [Per-trial order and database audits](results/resume-2027/locust/trials.json) · [Full-precision medians](results/resume-2027/locust/medians.json) · [Locust exports](results/resume-2027/locust/)

## Regression evidence

PostgreSQL regression passed **62** cases, including cancellation and fulfillment races, ignored duplicate requests, fault-injected rollback, ledger reconciliation, threshold crossing, recommendation approval, outbox deduplication, retry and lease recovery, and mock Telegram delivery. Playwright passed **8** cases across the local private dashboard (3), the API-backed read-only demo (2), and the static recruiter demo (3). Both frontend builds passed. There were no test failures or skips. Pytest reported one Starlette TestClient dependency deprecation. [Sanitized per-test results](results/resume-2027/regression.json)
