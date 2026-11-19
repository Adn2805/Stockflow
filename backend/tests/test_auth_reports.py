from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.auth import LoginSession, User, password_hasher, token_hash
from app.core.config import Settings
from app.main import create_app
from app.models import Inventory, StockMovement


@pytest.fixture
def accounts(database):
    password = token_urlsafe(20)
    with Session(database) as db, db.begin():
        db.add_all([
            User(username=role, role=role, password_hash=password_hasher.hash(password))
            for role in ("admin", "staff", "guest")
        ])
    settings = Settings(database_url=database.url.render_as_string(hide_password=False), write_token=None)
    with TestClient(create_app(settings)) as api:
        yield api, password


def login(api, role, password):
    response = api.post("/auth/login", json={"username": role, "password": password})
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert body["role"] == role and "password_hash" not in body
    return {"Authorization": "Bearer " + body["access_token"]}


def test_login_invalid_password_and_unknown_username_share_response(accounts):
    api, password = accounts
    wrong_password = api.post("/auth/login", json={"username": "admin", "password": "wrong"})
    wrong_user = api.post("/auth/login", json={"username": "missing", "password": password})
    assert wrong_password.status_code == wrong_user.status_code == 401
    assert wrong_password.json() == wrong_user.json()
    assert password not in wrong_user.text


def test_session_hash_expiration_and_logout(accounts, database):
    api, password = accounts
    headers = login(api, "admin", password)
    token = headers["Authorization"].split()[1]
    with Session(database) as db, db.begin():
        stored = db.get(LoginSession, token_hash(token))
        assert stored is not None and stored.token_hash != token
        assert stored.expires_at > datetime.now(UTC)
        db.execute(update(LoginSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    assert api.get("/orders", headers=headers).status_code == 401
    headers = login(api, "admin", password)
    assert api.get("/orders", headers=headers).status_code == 200
    assert api.post("/auth/logout", headers=headers).status_code == 204
    assert api.get("/orders", headers=headers).status_code == 401


def test_role_permissions_and_existing_order_workflow(accounts, warehouse):
    api, password = accounts
    admin = login(api, "admin", password)
    staff = login(api, "staff", password)
    guest = login(api, "guest", password)
    product = {"sku": "PHASE3", "name": "Work gloves", "price": "12.50"}
    assert api.post("/products", json=product).status_code == 401
    assert api.post("/products", headers=staff, json=product).status_code == 403
    created = api.post("/products", headers=admin, json=product)
    assert created.status_code == 201
    product_id = created.json()["id"]
    assert api.patch(f"/products/{product_id}", headers=staff, json={"name": "Changed"}).status_code == 403
    assert api.get("/products", headers=guest).json() == [created.json()]
    policy_path = f"/replenishment/policies/{product_id}/{warehouse.id}"
    policy = {"threshold": 0, "target": 10}
    for role in (staff, guest):
        assert api.get("/replenishment/recommendations", headers=role).status_code == 403
        assert api.patch(policy_path, json=policy, headers=role).status_code == 403
    assert api.patch(policy_path, json=policy, headers=admin).status_code == 200
    receipt = {"product_id": product_id, "warehouse_id": warehouse.id, "quantity": 5}
    assert api.post("/inventory/receipts", headers=guest, json=receipt).status_code == 403
    assert api.post("/inventory/receipts", headers=staff, json=receipt).status_code == 201
    assert api.get("/inventory").json()[0]["available"] == 5
    order = {"warehouse_id": warehouse.id, "customer_reference": "synthetic",
             "items": [{"product_id": product_id, "quantity": 2}]}
    assert api.post("/orders", headers=guest | {"Idempotency-Key": "guest"}, json=order).status_code == 403
    reserved = api.post("/orders", headers=staff | {"Idempotency-Key": "staff"}, json=order)
    assert reserved.status_code == 201, reserved.text
    path = f"/orders/{reserved.json()['id']}"
    assert api.get("/orders").status_code == 401
    assert api.get(path, headers=guest).status_code == 403
    assert api.post(path + "/cancel", headers=guest).status_code == 403
    assert api.post(path + "/fulfill", headers=staff).json()["status"] == "FULFILLED"
    assert api.get("/reports/reconciliation", headers=guest).status_code == 403
    assert api.get("/reports/stock-movements", headers=guest).status_code == 403
    assert api.get("/reports/reconciliation", headers=staff).json() == []
    history = api.get("/reports/stock-movements?limit=2", headers=staff).json()
    assert [row["movement_type"] for row in history] == ["FULFILLMENT", "RESERVATION"]
    assert all(row["order_id"] == reserved.json()["id"] for row in history)


def test_reconciliation_reports_multiple_discrepancies_without_mutating_stock(client, database, warehouse):
    def receipt(sku):
        created = client.post("/products", json={"sku": sku, "name": sku, "price": "1.00"})
        product_id = created.json()["id"]
        assert client.post("/inventory/receipts", json={
            "warehouse_id": warehouse.id, "product_id": product_id, "quantity": 10,
        }).status_code == 201
        return product_id

    first, second = receipt("FIRST"), receipt("SECOND")
    assert client.get("/reports/reconciliation").json() == []
    with database.begin() as db:
        db.execute(update(Inventory).where(Inventory.product_id == first).values(on_hand=9))
        db.execute(update(Inventory).where(Inventory.product_id == second).values(reserved=2))
    expected = [
        {"product_id": first, "warehouse_id": warehouse.id, "actual_on_hand": 9,
         "expected_on_hand": 10, "actual_reserved": 0, "expected_reserved": 0},
        {"product_id": second, "warehouse_id": warehouse.id, "actual_on_hand": 10,
         "expected_on_hand": 10, "actual_reserved": 2, "expected_reserved": 0},
    ]
    assert client.get("/reports/reconciliation").json() == expected
    assert client.get("/reports/reconciliation?offset=1&limit=1").json() == expected[1:]
    history = client.get(f"/reports/stock-movements?product_id={first}&warehouse_id={warehouse.id}").json()
    assert len(history) == 1 and history[0]["delta_on_hand"] == 10
    with Session(database) as db:
        assert db.execute(text("SELECT on_hand, reserved FROM inventory ORDER BY product_id")).all() == [
            (9, 0), (10, 2),
        ]
        assert len(db.scalars(select(StockMovement)).all()) == 2


def test_cors_allows_only_configured_origins():
    app = create_app(Settings(
        database_url="postgresql+psycopg://localhost/unused",
        cors_origins=["http://localhost:5173"],
    ))
    with TestClient(app) as api:
        approved = {"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"}
        assert api.options("/auth/login", headers=approved).headers["Access-Control-Allow-Origin"] == approved["Origin"]
        unapproved = approved | {"Origin": "https://unapproved.invalid"}
        assert "Access-Control-Allow-Origin" not in api.options("/auth/login", headers=unapproved).headers
