# StockFlow Phase 4 benchmarks

## Reproduce locally

Run from the repository root with Python 3.12 and a loopback PostgreSQL test database. Follow the [database setup](../README.md#tests) and export `TEST_DATABASE_URL` pointing to a database whose name ends in `_test`. Install the benchmark dependencies in the backend virtual environment.

```sh
python -m pip install -r benchmarks/requirements.txt
python benchmarks/concurrency.py --output benchmarks/local-results/concurrency.json
python benchmarks/performance.py --seconds 10 --repeats 3 --output benchmarks/local-results/locust
```

Each scenario creates an empty random schema, applies Alembic migrations, inserts deterministic synthetic data, runs a single Uvicorn process bound to loopback, checks the database, and removes the schema. The loopback ports default to 58082 for the concurrency harness and 58083 for Locust. Use the corresponding `--port` option if one is in use.

## Concurrency results

| Scenario | Attempts | HTTP 201 | HTTP 200 replays | HTTP 409 stock rejections | Burst wall time |
| --- | ---: | ---: | ---: | ---: | ---: |
| One SKU / run 1 | 500 | 100 | 0 | 400 | 9.0594 s |
| One SKU / run 2 | 500 | 100 | 0 | 400 | 9.7555 s |
| Two products / opposite input order | 32 | 5 | 0 | 27 | 0.5811 s |
| Identical requests / shared key | 32 | 1 | 31 | 0 | 0.5820 s |

All HTTP requests were released through one async start gate. The API and database controlled actual socket scheduling and transaction admission. Each single-SKU attempt used a distinct key and requested one of 100 available units. In both runs, the database ended with 100 on hand, 100 reserved, zero available, and exactly 100 orders, items, and reservation movements. The two-product case requested quantities of two and one from balances of ten each. Only five complete orders committed. The shared-key run committed one order and every successful response referenced it. Audits found zero duplicate keys, empty orders, invalid balances, ledger mismatches, reservation mismatches, and invalid order movement histories. [Raw concurrency results](results/concurrency.json)

## Locust methodology

Each trial starts with 1,000 products, 2 warehouses, 10,000 fulfilled historical orders, 22,000 historical movements, and 100,000 units on hand. The fixture starts each product/warehouse pair at 55 units, then records five prior one-unit fulfillments. Each of 10, 25, 50, and 100 users was tested in three independent 10-second trials with no warm-up exclusion. Users spawn at the target user count per second and wait 50 ms between requests. The per-user task cycle is five paginated product reads, two inventory reads, and three distinct-key order attempts against the same SKU in one of two warehouses. Orders request one or two units. The benchmark deliberately allows the hot SKU to sell out so it also measures how the API handles stock rejection.

Locust exports the final aggregate and per-route statistics after in-flight requests finish. A pilot exposed a timing gap between its periodic CSV snapshot and the final order counts, so the figures below use the final export. An HTTP 409 counts as an expected rejection only when the API reports insufficient stock. The rejection rate denominator is order attempts. Unexpected error rates use all HTTP requests. Database audits run before and after each trial. The monitor samples API connections every 200 ms for lock waits and reads PostgreSQL's database-wide deadlock counter. Brief waits can occur between samples.

## Measured Locust results

| Locust users | Median req/s | Median p50 | Median p95 | Unexpected errors | Median stock rejection rate |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 98.87 | 38 ms | 120 ms | 0.00% | 77.36% |
| 25 | 97.56 | 190 ms | 370 ms | 0.00% | 79.02% |
| 50 | 112.17 | 350 ms | 650 ms | 0.00% | 81.25% |
| 100 | 105.95 | 780 ms | 1500 ms | 0.00% | 80.71% |

All 12 trials passed. They recorded 11575 HTTP requests, including 3458 order attempts. 721 orders committed and 2737 were rejected for insufficient stock. There were zero unexpected HTTP errors and no increase in the PostgreSQL deadlock counter. All trials retained 100,000 on-hand units and passed the order, inventory, and ledger audits.

The monitor observed a database lock wait in 46 of 651 samples, including 46 samples with a transaction-ID lock wait. At most 4 API connections were waiting in one sample.

[Trial audits](results/locust/trials.json), [unrounded medians](results/locust/medians.json), [example final Locust CSV](results/locust/u100-run1_stats.csv), and [query plan](results/locust/inventory-lock-plan.json).

## Conditions and limitations

Measured on 19 November 2026 (IST) on a Windows 11 host (build 26300) with an Intel Core i5-1235U, 12 logical CPUs, and 15.68 GiB of RAM. Python 3.12.13 ran the load generators and single-process Uvicorn API on the host. PostgreSQL 17.12 ran in the local Docker Linux container. The measured backend application was commit `019d1897322496b53ea40edb829dff77ceabed6d`, with a clean `backend/app` directory. The Phase 4 harness was run from the working tree.

These short local trials include startup ramp and share host resources with the API and PostgreSQL. They measure this synthetic workload and configuration. Once the hot SKU sells out, much of the order traffic exercises the rejection path. No performance gain was computed. The stored `EXPLAIN (ANALYZE, BUFFERS)` query inspects the inventory row-locking lookup on the seeded fixture. It ran before load and used the warehouse/product index to lock two rows in 0.072 ms of execution time. Contention was measured separately during the trials.

The GitHub Actions definition covers the regression suite, HTTP concurrency invariant checks, and browser smoke tests. The full Locust matrix is a separate local benchmark. The workflow passed local static validation with actionlint 1.7.12. It has yet to run on GitHub.
