# StockFlow

StockFlow manages stock receipts and order fulfillment across warehouses. When two customers order the last unit, the system must accept only one reservation. StockFlow commits the order, inventory changes, and ledger entries in one PostgreSQL transaction so a failure cannot leave stock and order history out of sync.

[Live recruiter demo](https://stockflow-adn2805.pages.dev/) · [Benchmark methodology and results](benchmarks/resume-2027.md) · [Raw benchmark evidence](benchmarks/results/resume-2027/)

## Engineering design

- **Order transactions.** FastAPI locks inventory rows in product ID order. PostgreSQL enforces stock bounds and unique idempotency keys. An equivalent retry returns the existing order. Cancellation releases the reservation, and fulfillment consumes it.
- **Inventory and reconciliation.** Receipts and order actions write stock movements in the same transaction as balance changes. The reconciliation query compares on-hand and reserved balances against the ledger. Order lines retain decimal price snapshots.
- **Replenishment and notifications.** A threshold breach creates a draft recommendation and a notification outbox row inside the inventory transaction. A separate worker claims committed messages, retries transient Telegram failures, and records delivery status. An administrator approves recommendations without placing a purchase order.
- **Dashboard and access.** React and TypeScript call the FastAPI API. Staff can receive stock and process orders. Administrators also manage products and replenishment policies. Guest access is read-only.

**Stack** · Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL, Alembic, React, TypeScript, Vite, Docker Compose, pytest, Playwright, and Locust.

## Verified results

Two runs against the local FastAPI and PostgreSQL stack each released **500 competing order attempts** against 100 units. Each run committed **100 reservations**, rejected **400** for insufficient stock, and oversold **0** units. A shared-key burst of 32 requests created one order and returned 31 idempotent replays. [Concurrency audits](benchmarks/results/resume-2027/concurrency.json)

Locust measured **8,119 successful reservations** across 12 trials, with zero stock rejections or unexpected errors. Each row below is the median of three trials for HTTP 201 responses. [Per-trial results](benchmarks/results/resume-2027/locust/trials.json)

| Locust users | Successful orders/s | p50 | p95 | p99 |
| ---: | ---: | ---: | ---: | ---: |
| 10 | 68.06 | 82 ms | 160 ms | 210 ms |
| 25 | 62.37 | 340 ms | 580 ms | 680 ms |
| 50 | 48.99 | 920 ms | 1,300 ms | 1,800 ms |
| 100 | 44.30 | 2,100 ms | 3,300 ms | 4,800 ms |

**62 backend and 8 Playwright tests passed**, covering stock contention, rollback, cancellation, reconciliation, replenishment, and outbox retries. [Per-test evidence](benchmarks/results/resume-2027/regression.json) · [CI workflow](.github/workflows/ci.yml)

## Run locally

Copy `.env.example` to `.env`, set a random hexadecimal `POSTGRES_PASSWORD`, and leave `WRITE_TOKEN` empty to use account authentication. From the repository root:

```sh
docker compose up -d --wait db
docker compose run --rm --build api alembic upgrade head
docker compose up -d api
docker compose run --rm api python -m app.create_user admin-user admin
docker compose exec db psql -U stockflow -d stockflow -c "INSERT INTO warehouses (name, location) VALUES ('Central', 'Local development') ON CONFLICT (name) DO NOTHING;"
cd frontend
npm ci
npm run dev
```

Open the dashboard at `http://127.0.0.1:5173` and sign in with the account created above. Swagger is at `http://localhost:8000/docs` by default. Vite proxies API requests to the root `.env` value of `API_PORT`. Keep Telegram settings in the worker's private environment. [Telegram setup and recovery](docs/replenishment.md)

### Tests and benchmarks

Use a Python 3.12 virtual environment. Create the dedicated test database once, then set `TEST_DATABASE_URL` to `postgresql+psycopg://stockflow:<password>@127.0.0.1:5432/stockflow_test` with your local password and database port.

```sh
docker compose exec db createdb -U stockflow stockflow_test
python -m pip install -r benchmarks/requirements.txt
(cd backend && python -m pytest -ra)
python benchmarks/concurrency.py --output benchmarks/local-results/concurrency.json
python benchmarks/performance.py --workload successful-orders --seconds 12 --repeats 3 --output benchmarks/local-results/locust
```

From `frontend`, run `npx playwright install chromium`, then `npm test`, `npm run test:demo`, and `npm run build:static && npm run test:static`. Set `STOCKFLOW_TEST_PYTHON` if the test runner needs an explicit path to the virtual environment's Python. [Full benchmark conditions](benchmarks/resume-2027.md)

## Demo and measurement limits

The public Cloudflare Pages site is read-only, with a 320-order synthetic snapshot and browser simulations for concurrency, replenishment, and the Telegram workflow. It has no backend connection and sends no messages. Authentication, stock writes, and real Telegram delivery run on the private local stack. Telegram delivery is at-least-once, so a retry after a lost acknowledgment can duplicate a message. The benchmarks use synthetic data, short trials, and one local API process. They measure the documented workload and environment. [Deployment and verification](docs/deployment.md)
