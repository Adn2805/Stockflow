import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.seed_demo import seed


def test_hosted_demo_requires_safe_environment():
    url = "postgresql+psycopg://stockflow_demo_reader@demo.invalid/stockflow?sslmode=verify-full"
    settings = dict(public_demo=True, database_url=url, write_token=None, cors_origins=["https://demo.invalid"])
    Settings(**settings)
    for override in (
        {"write_token": "x" * 32},
        {"database_url": url.replace("verify-full", "require")},
        {"database_url": url.replace("stockflow_demo_reader", "owner")},
        {"cors_origins": []},
        {"cors_origins": ["http://demo.invalid"]},
    ):
        with pytest.raises(ValidationError):
            Settings(**(settings | override))


def test_public_demo_reads_consistent_synthetic_data_and_rejects_all_mutations(database):
    with Session(database) as session:
        seed(session)
        with pytest.raises(ValueError, match="fresh, empty database"):
            seed(session)

    origin = "https://demo.invalid"
    settings = Settings(
        public_demo=True, write_token=None, cors_origins=[origin],
        database_url=database.url.render_as_string(hide_password=False),
    )
    with TestClient(create_app(settings)) as api:
        assert api.get("/live").json() == {"status": "ok"}
        assert api.get("/health").json() == {"status": "ok"}
        assert len(api.get("/products").json()) == 5
        assert len(api.get("/warehouses").json()) == 2
        assert len(api.get("/inventory").json()) == 10
        orders = api.get("/orders").json()
        assert {row["status"] for row in orders} == {"RESERVED", "CANCELLED", "FULFILLED"}
        assert len(orders) == 4
        assert all(row["customer_reference"].startswith("Demo customer ") for row in orders)
        assert api.get(f"/orders/{orders[0]['id']}").status_code == 200
        movements = api.get("/reports/stock-movements").json()
        assert len(movements) == 20
        assert api.get("/reports/reconciliation").json() == []
        for method, route in (
            ("POST", "/auth/login"), ("POST", "/auth/logout"), ("POST", "/products"),
            ("PATCH", "/products/1"), ("POST", "/inventory/receipts"), ("POST", "/orders"),
            ("POST", "/orders/1/cancel"), ("POST", "/orders/1/fulfill"), ("DELETE", "/orders/1"),
        ):
            response = api.request(method, route, json={}, headers={"Origin": origin, "Authorization": "Bearer nope"})
            assert response.status_code == 403
            assert response.headers["Access-Control-Allow-Origin"] == origin
        assert "Access-Control-Allow-Origin" not in api.get(
            "/orders", headers={"Origin": "https://other.invalid"}
        ).headers
        assert api.get("/orders").json() == orders
        with api.app.state.engine.connect() as connection:
            assert connection.scalar(text("SHOW transaction_read_only")) == "on"
            with pytest.raises(DBAPIError) as exc:
                connection.execute(text("UPDATE products SET name = name"))
            assert exc.value.orig.sqlstate == "25006"
