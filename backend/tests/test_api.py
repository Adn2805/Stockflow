from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.models import Inventory, Product, StockMovement

PRODUCT = {"sku": " sku-01 ", "name": "Safety shoes", "price": "12.30"}


def create_product(client, **fields):
    response = client.post("/products", json=PRODUCT | fields)
    assert response.status_code == 201, response.text
    return response.json()


def test_product_lifecycle(client, database):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/products").json() == []
    product = create_product(client, description="Blue")
    assert product["sku"] == "SKU-01"
    assert product["price"] == "12.30"
    path = f"/products/{product['id']}"
    assert client.get(path).json() == product
    response = client.patch(path, json={"price": "12.35", "description": None})
    assert response.status_code == 200
    assert response.json() == product | {"price": "12.35", "description": None}
    with Session(database) as session:
        assert session.get(Product, product["id"]).price == Decimal("12.35")

    second = create_product(client, sku="SKU-02")
    assert client.get("/products", params={"limit": 1, "offset": 1}).json() == [second]
    assert client.get("/products/999").status_code == 404
    assert client.patch("/products/999", json={"name": "Missing"}).status_code == 404


def test_duplicate_sku_is_case_insensitive(client):
    first = create_product(client)
    second = create_product(client, sku="other")
    assert client.post("/products", json=PRODUCT | {"sku": "sku-01"}).status_code == 409
    path = f"/products/{second['id']}"
    assert client.patch(path, json={"sku": first["sku"]}).status_code == 409
    assert client.get(path).json() == second


def test_receipts_accumulate_and_write_movements(client, database, warehouse):
    product = create_product(client)
    key = {"product_id": product["id"], "warehouse_id": warehouse.id}
    assert client.get("/warehouses").json()[0]["id"] == warehouse.id
    assert client.get("/inventory").json() == []
    for quantity, total in [(8, 8), (4, 12)]:
        response = client.post("/inventory/receipts", json=key | {"quantity": quantity})
        assert response.status_code == 201, response.text
        assert response.json() == key | {"on_hand": total, "reserved": 0, "available": total}

    assert client.get("/inventory", params=key).json() == [response.json()]
    assert client.get("/inventory", params={"warehouse_id": warehouse.id + 1}).json() == []
    assert client.post("/inventory/receipts", json=key | {"product_id": 999, "quantity": 1}).status_code == 404
    assert client.post("/inventory/receipts", json=key | {"warehouse_id": 999, "quantity": 1}).status_code == 404
    with Session(database) as session:
        rows = session.scalars(select(StockMovement).order_by(StockMovement.id)).all()
        assert [(m.delta_on_hand, m.delta_reserved, m.movement_type) for m in rows] == [
            (8, 0, "RECEIPT"), (4, 0, "RECEIPT")
        ]
        with pytest.raises(IntegrityError):
            session.execute(text("UPDATE inventory SET reserved = on_hand + 1"))


def test_receipt_rolls_back_if_movement_fails(client, database, warehouse):
    product = create_product(client)
    data = {"product_id": product["id"], "warehouse_id": warehouse.id, "quantity": 3}
    assert client.post("/inventory/receipts", json=data).status_code == 201
    with database.begin() as connection:
        connection.execute(text(
            "ALTER TABLE stock_movements ADD CONSTRAINT test_reject_four CHECK (delta_on_hand <> 4)"
        ))
    response = client.post("/inventory/receipts", json=data | {"quantity": 4})
    assert response.status_code == 500
    assert response.json() == {"detail": "Database operation failed"}
    with Session(database) as session:
        assert session.get(Inventory, (product["id"], warehouse.id)).on_hand == 3
        assert session.scalar(select(func.count()).select_from(StockMovement)) == 1


def test_concurrent_first_receipts_preserve_each_increment(client, warehouse, database):
    product = create_product(client)
    key = {"product_id": product["id"], "warehouse_id": warehouse.id}
    start = Barrier(4, timeout=10)

    def receive(quantity):
        start.wait()
        return client.post("/inventory/receipts", json=key | {"quantity": quantity})

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(receive, [1, 2, 3, 4]))
    assert [response.status_code for response in responses] == [201] * 4
    assert client.get("/inventory", params=key).json()[0]["on_hand"] == 10
    with Session(database) as session:
        assert sorted(session.scalars(select(StockMovement.delta_on_hand))) == [1, 2, 3, 4]


def test_receipt_overflow_keeps_balance_and_history(client, database, warehouse):
    product = create_product(client)
    key = {"product_id": product["id"], "warehouse_id": warehouse.id}
    maximum = 2**63 - 1
    assert client.post("/inventory/receipts", json=key | {"quantity": maximum}).status_code == 201
    assert client.post("/inventory/receipts", json=key | {"quantity": 1}).status_code == 409
    assert client.get("/inventory").json()[0]["on_hand"] == maximum
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(StockMovement)) == 1


@pytest.fixture
def validation_client():
    # Invalid requests and authorization short-circuit before any database connection.
    settings = Settings(database_url="postgresql+psycopg://localhost/unused", write_token="x" * 32)
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.mark.parametrize("fields", [
    {"price": "-0.01"}, {"price": "1.234"}, {"price": "10000000000"},
    {"price": "NaN"}, {"sku": "?"}, {"name": "   "}, {"name": "bad\x00name"}, {"unknown": True},
])
def test_invalid_product(validation_client, fields):
    response = validation_client.post(
        "/products", json=PRODUCT | fields, headers={"Authorization": "Bearer " + "x" * 32}
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "Invalid request"


@pytest.mark.parametrize("method,path,body", [
    ("PATCH", "/products/1", {}),
    ("PATCH", "/products/1", {"name": None}),
    ("GET", "/products/0", None),
    ("GET", "/inventory?limit=101", None),
    ("POST", "/inventory/receipts", {"product_id": 1, "warehouse_id": 1, "quantity": 0}),
    ("POST", "/inventory/receipts", {"product_id": 1, "warehouse_id": 1, "quantity": True}),
    ("POST", "/inventory/receipts", {"product_id": 1, "warehouse_id": 1, "quantity": "2"}),
    ("POST", "/inventory/receipts", {"product_id": 2**63, "warehouse_id": 1, "quantity": 2}),
])
def test_invalid_request(validation_client, method, path, body):
    response = validation_client.request(
        method, path, json=body, headers={"Authorization": "Bearer " + "x" * 32}
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/products", PRODUCT),
    ("PATCH", "/products/1", {"name": "Changed"}),
    ("POST", "/inventory/receipts", {"product_id": 1, "warehouse_id": 1, "quantity": 1}),
])
def test_all_mutations_require_write_token(validation_client, method, path, body):
    for headers in ({}, {"Authorization": "Bearer wrong"}):
        response = validation_client.request(method, path, json=body, headers=headers)
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_missing_server_token_disables_writes(monkeypatch):
    monkeypatch.delenv("WRITE_TOKEN", raising=False)
    settings = Settings(database_url="postgresql+psycopg://localhost/unused")
    with TestClient(create_app(settings)) as client:
        assert client.post("/products", json=PRODUCT).status_code == 403


def test_oversized_request_is_rejected(validation_client):
    response = validation_client.post(
        "/products",
        json=PRODUCT | {"description": "x" * (32 * 1024)},
        headers={"Authorization": "Bearer " + "x" * 32},
    )
    assert response.status_code == 413
