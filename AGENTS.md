# StockFlow engineering rules

- Inspect the repository and existing tests before editing. Stay in the approved phase and obtain explicit approval before starting the next one or pushing to GitHub.
- Keep the FastAPI backend a modular monolith. Use PostgreSQL, SQLAlchemy 2, Pydantic, and Alembic. Apply migrations explicitly.
- Store prices as decimals. Enforce inventory bounds in PostgreSQL and commit each stock change with its movement in one transaction.
- Validate requests and authorize mutations. Keep credentials out of source, responses, and logs. Use isolated PostgreSQL databases for integration, concurrency, and fault-injection tests.
- In the order phase, enforce idempotency with a database constraint, acquire inventory locks consistently, and validate order state transitions inside the transaction.
- Preserve working behavior and document significant decisions. Report commands and actual results, including failures and gaps. Never invent benchmarks or deployment evidence.
- Use free local infrastructure. Obtain approval before irreversible actions or publishing. Never activate billable services.
