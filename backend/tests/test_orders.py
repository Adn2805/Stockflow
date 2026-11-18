from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Inventory, Order, OrderItem, StockMovement


@pytest.fixture
def catalog(client, warehouse):
    def seed(*quantities):
        items = []
        for index, quantity in enumerate(quantities):
            product = client.post("/products", json={
                "sku": f"ITEM-{index}", "name": "Work gloves", "price": "12.30",
            })
            assert product.status_code == 201, product.text
            product_id = product.json()["id"]
            receipt = client.post("/inventory/receipts", json={
                "product_id": product_id, "warehouse_id": warehouse.id, "quantity": quantity,
            })
            assert receipt.status_code == 201, receipt.text
            items.append({"product_id": product_id, "quantity": 1})
        return {"customer_reference": "customer-1", "warehouse_id": warehouse.id, "items": items}
    return seed


def submit(client, data, key):
    return client.post("/orders", json=data, headers={"Idempotency-Key": key})


def simulate_concurrency(requests):
    start = Barrier(len(requests), timeout=15)

    def call(request):
        start.wait()
        return request()

    with ThreadPoolExecutor(max_workers=len(requests)) as pool:
        return list(pool.map(call, requests))


def assert_ledger(database, expected, orders, item_count, order_movements):
    with Session(database) as db:
        balances = db.scalars(select(Inventory).order_by(Inventory.product_id)).all()
        assert [(row.on_hand, row.reserved) for row in balances] == expected
        for balance in balances:
            on_hand, reserved = db.execute(
                select(func.sum(StockMovement.delta_on_hand), func.sum(StockMovement.delta_reserved))
                .where(StockMovement.product_id == balance.product_id,
                       StockMovement.warehouse_id == balance.warehouse_id)
            ).one()
            assert (on_hand, reserved) == (balance.on_hand, balance.reserved)
        assert db.scalar(select(func.count()).select_from(Order)) == orders
        assert db.scalar(select(func.count()).select_from(OrderItem)) == item_count
        assert db.scalar(select(func.count()).select_from(StockMovement)
                         .where(StockMovement.order_id.is_not(None))) == order_movements


@pytest.mark.parametrize("action,status,balance", [
    ("cancel", "CANCELLED", (5, 0)), ("fulfill", "FULFILLED", (4, 0)),
])
def test_order_lifecycle(client, database, catalog, action, status, balance):
    data = catalog(5, 5)
    started = submit(client, data, "example-key")
    assert started.status_code == 201, started.text
    original = started.json()
    assert original["status"] == "RESERVED"
    assert [item["unit_price_snapshot"] for item in original["items"]] == ["12.30", "12.30"]
    order_path = f"/orders/{original['id']}"
    assert client.get("/orders?limit=1").json() == [original]
    assert client.get("/orders?offset=1").json() == []
    assert client.get(order_path).json() == original
    assert client.get("/orders/999").status_code == 404

    product_id = data["items"][0]["product_id"]
    assert client.patch(f"/products/{product_id}", json={"price": "99.99"}).status_code == 200
    assert client.get(order_path).json() == original

    finished = client.post(f"{order_path}/{action}")
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == status
    assert client.post(f"{order_path}/{action}").json() == finished.json()
    opposed = "fulfill" if action == "cancel" else "cancel"
    assert client.post(f"{order_path}/{opposed}").status_code == 409
    replay = submit(client, data | {"items": data["items"][::-1]}, "example-key")
    assert replay.status_code == 200
    assert replay.json() == finished.json()
    assert submit(client, data | {"warehouse_id": 999}, "example-key").status_code == 409
    assert_ledger(database, [balance, balance], 1, 2, 4)


def test_insufficient_second_item_rolls_back_and_key_can_retry(client, database, catalog):
    data = catalog(5, 1)
    data["items"][1]["quantity"] = 2
    assert submit(client, data, "retry").status_code == 409
    assert_ledger(database, [(5, 0), (1, 0)], 0, 0, 0)
    receipt = client.post("/inventory/receipts", json={
        "product_id": data["items"][1]["product_id"], "warehouse_id": data["warehouse_id"],
        "quantity": 1,
    })
    assert receipt.status_code == 201
    assert submit(client, data, "retry").status_code == 201
    assert_ledger(database, [(5, 1), (2, 2)], 1, 2, 2)


def test_database_failure_rolls_back_order_and_all_stock_changes(client, database, catalog):
    data = catalog(5, 5)
    with database.begin() as db:
        db.execute(text("""
            ALTER TABLE stock_movements ADD CONSTRAINT reject_one_reservation
            CHECK (movement_type <> 'RESERVATION' OR product_id <> 2)
        """))
    failed = submit(client, data, "rollback")
    assert failed.status_code == 500, failed.text
    assert failed.json() == {"detail": "Database operation failed"}
    assert_ledger(database, [(5, 0), (5, 0)], 0, 0, 0)
    with database.begin() as db:
        db.execute(text("ALTER TABLE stock_movements DROP CONSTRAINT reject_one_reservation"))
    assert submit(client, data, "rollback").status_code == 201
    assert_ledger(database, [(5, 1), (5, 1)], 1, 2, 2)


def test_fulfillment_failure_preserves_reservation(client, database, catalog):
    data = catalog(5, 5)
    order = submit(client, data, "fulfill-failure").json()
    with database.begin() as db:
        db.execute(text("""
            ALTER TABLE stock_movements ADD CONSTRAINT reject_fulfillment
            CHECK (movement_type <> 'FULFILLMENT')
        """))
    assert client.post(f"/orders/{order['id']}/fulfill").status_code == 500
    assert client.get(f"/orders/{order['id']}").json()["status"] == "RESERVED"
    assert_ledger(database, [(5, 1), (5, 1)], 1, 2, 2)


def test_competing_orders_for_one_sku_do_not_oversell(client, database, catalog):
    data = catalog(5)
    responses = simulate_concurrency([
        lambda key=key: submit(client, data, f"sku-race-{key}") for key in range(16)
    ])
    assert sorted(r.status_code for r in responses) == [201] * 5 + [409] * 11
    assert_ledger(database, [(5, 5)], 5, 5, 5)


def test_multi_product_orders_with_reversed_item_order(client, database, catalog):
    data = catalog(7, 7)
    data["items"][0]["quantity"] = 2
    responses = simulate_concurrency([
        lambda key=key: submit(
            client, data if key % 2 else data | {"items": data["items"][::-1]}, f"multi-{key}"
        ) for key in range(8)
    ])
    assert sorted(r.status_code for r in responses) == [201] * 3 + [409] * 5
    assert_ledger(database, [(7, 6), (7, 3)], 3, 6, 6)


def test_concurrent_identical_retries_create_one_order(client, database, catalog):
    data = catalog(10)
    responses = simulate_concurrency([lambda: submit(client, data, "same-key")] * 8)
    assert sorted(r.status_code for r in responses) == [200] * 7 + [201]
    assert all(response.json() == responses[0].json() for response in responses)
    assert_ledger(database, [(10, 1)], 1, 1, 1)


def test_concurrent_key_mismatch_creates_one_order(client, database, catalog):
    data = catalog(5)
    responses = simulate_concurrency([
        lambda: submit(client, data, "mismatch"),
        lambda: submit(client, data | {"customer_reference": "other"}, "mismatch"),
    ])
    assert sorted(r.status_code for r in responses) == [201, 409]
    assert_ledger(database, [(5, 1)], 1, 1, 1)


def test_concurrent_cancellation_and_fulfillment(client, database, catalog):
    order = submit(client, catalog(5), "transition-race").json()
    path = f"/orders/{order['id']}"
    responses = simulate_concurrency([
        lambda: client.post(f"{path}/cancel"),
        lambda: client.post(f"{path}/fulfill"),
    ])
    assert sorted(r.status_code for r in responses) == [200, 409]
    winner = "CANCELLED" if responses[0].status_code == 200 else "FULFILLED"
    assert client.get(path).json()["status"] == winner
    assert_ledger(database, [(5 if winner == "CANCELLED" else 4, 0)], 1, 1, 2)


def test_order_input_and_authorization(client, database, catalog):
    data = catalog(5)
    no_token = {"Authorization": "", "Idempotency-Key": "key"}
    assert client.post("/orders", json=data, headers=no_token).status_code == 401
    assert client.post("/orders/1/cancel", headers=no_token).status_code == 401
    assert client.post("/orders/1/fulfill", headers=no_token).status_code == 401
    assert client.post("/orders", json=data).status_code == 422
    assert submit(client, data, "invalid key").status_code == 422
    assert submit(client, data | {"items": data["items"] * 2}, "key").status_code == 422
    assert submit(client, data | {"items": [data["items"][0] | {"quantity": 0}]}, "key").status_code == 422
    assert submit(client, data | {"warehouse_id": 999}, "key").status_code == 404
    assert submit(client, data | {"items": [{"product_id": 999, "quantity": 1}]}, "key").status_code == 404
    assert_ledger(database, [(5, 0)], 0, 0, 0)


def test_retry_after_lost_response_does_not_reserve_twice(client, database, catalog):
    data = catalog(2)
    # The transaction commits, but the caller discards the original response.
    assert submit(client, data, "lost-response").status_code == 201
    replay = submit(client, data, "lost-response")
    assert replay.status_code == 200
    assert replay.json() == client.get("/orders").json()[0]
    assert_ledger(database, [(2, 1)], 1, 1, 1)


def test_concurrent_orders_with_mixed_quantities(client, database, catalog):
    data = catalog(6)
    small = data
    large = data | {"items": [data["items"][0] | {"quantity": 5}]}
    responses = simulate_concurrency([
        lambda: submit(client, large, "large"),
        lambda: submit(client, small, "small"),
        lambda: submit(client, small, "other-small"),
    ])
    codes = [response.status_code for response in responses]
    assert codes in ([201, 201, 409], [201, 409, 201], [409, 201, 201])
    assert_ledger(database, [(6, 6 if codes[0] == 201 else 2)], 2, 2, 2)
