from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from time import monotonic, sleep
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from io import BytesIO

import pytest
from sqlalchemy import event, func, select, text, update
from sqlalchemy.orm import sessionmaker

from app.models import Inventory
from app.replenishment import OutboxMessage
from app.telegram_worker import DeliveryError, claim_message, deliver_one, telegram_sender


@pytest.fixture
def stock(client, warehouse):
    created = client.post("/products", json={"sku": "ALERT", "name": "Work boots", "price": "40.00"})
    assert created.status_code == 201
    product_id = created.json()["id"]
    key = {"product_id": product_id, "warehouse_id": warehouse.id}
    assert client.post("/inventory/receipts", json=key | {"quantity": 10}).status_code == 201
    policy = client.patch(f"/replenishment/policies/{product_id}/{warehouse.id}",
                          json={"threshold": 5, "target": 20})
    assert policy.status_code == 200, policy.text
    return key


def order(client, stock, key, quantity):
    return client.post("/orders", headers={"Idempotency-Key": key}, json={
        "customer_reference": "demo", "warehouse_id": stock["warehouse_id"],
        "items": [{"product_id": stock["product_id"], "quantity": quantity}],
    })


def recommendations(client):
    response = client.get("/replenishment/recommendations")
    assert response.status_code == 200, response.text
    return response.json()


def test_threshold_equality_repeated_orders_and_fulfillment(client, stock):
    assert order(client, stock, "at-threshold", 5).status_code == 201
    assert recommendations(client) == []
    crossed = order(client, stock, "below", 1)
    assert crossed.status_code == 201
    assert order(client, stock, "below", 1).status_code == 200
    assert order(client, stock, "another", 1).status_code == 201
    draft, = recommendations(client)
    assert (draft["available"], draft["threshold"], draft["suggested_quantity"]) == (3, 5, 17)
    assert draft["notification_status"] == "pending"
    assert client.post(f"/orders/{crossed.json()['id']}/fulfill").status_code == 200
    assert recommendations(client) == [draft]


def test_recovery_cancels_pending_and_new_crossing_rearms(client, stock):
    first = order(client, stock, "first-crossing", 6)
    assert first.status_code == 201
    old, = recommendations(client)
    assert client.post(f"/orders/{first.json()['id']}/cancel").status_code == 200
    recovered, = recommendations(client)
    assert recovered["resolved_at"] is not None
    assert recovered["notification_status"] == "cancelled"
    assert client.post(f"/replenishment/recommendations/{old['id']}/approve").status_code == 409
    assert order(client, stock, "new-crossing", 7).status_code == 201
    current, prior = recommendations(client)
    assert current["id"] != prior["id"] and current["resolved_at"] is None
    receipt = client.post("/inventory/receipts", json=stock | {"quantity": 2})
    assert receipt.status_code == 201 and receipt.json()["available"] == 5
    assert client.get("/replenishment/recommendations?active_only=true").json() == []


def test_approval_is_idempotent_and_does_not_change_stock(client, stock):
    assert order(client, stock, "draft", 6).status_code == 201
    draft, = recommendations(client)
    before = client.get("/inventory").json()
    path = f"/replenishment/recommendations/{draft['id']}/approve"
    response = client.post(path)
    assert response.status_code == 200 and response.json()["approved_at"]
    assert client.post(path).json() == response.json()
    assert client.get("/inventory").json() == before
    assert order(client, stock, "after-approval", 1).status_code == 201
    assert recommendations(client)[0]["suggested_quantity"] == draft["suggested_quantity"]


def test_concurrent_crossings_produce_one_draft_and_outbox(client, stock, database):
    assert order(client, stock, "approach", 5).status_code == 201
    gate = Barrier(4, timeout=10)

    def reserve(index):
        gate.wait()
        return order(client, stock, f"concurrent-{index}", 1)

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert [result.status_code for result in pool.map(reserve, range(4))] == [201] * 4
    draft, = recommendations(client)
    assert (draft["available"], draft["suggested_quantity"]) == (1, 19)
    sessions = sessionmaker(database)
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(OutboxMessage)) == 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: claim_message(sessions), range(4)))
    assert sum(claim is not None for claim in claims) == 1


def test_rollback_discards_draft_and_outbox(client, stock, database):
    with database.begin() as db:
        db.execute(text("ALTER TABLE stock_movements ADD CONSTRAINT deny_reservation "
                        "CHECK (movement_type <> 'RESERVATION')"))
    assert order(client, stock, "rollback-alert", 6).status_code == 500
    assert recommendations(client) == []
    assert client.get("/inventory").json()[0]["available"] == 10
    with database.connect() as db:
        assert db.scalar(select(func.count()).select_from(OutboxMessage)) == 0


def test_failure_retry_and_committed_claim(client, stock, database):
    assert order(client, stock, "notify", 6).status_code == 201
    sessions = sessionmaker(database)

    def unavailable(message):
        with sessions() as db:
            assert db.scalar(select(OutboxMessage.status)) == "sending"
        for value in ("Work boots", "Central", "Available: 4", "threshold: 5", "reorder: 16"):
            assert value in message
        raise DeliveryError("telegram_rate_limit", delay=60)

    assert deliver_one(sessions, unavailable)
    assert recommendations(client)[0]["notification_status"] == "retry"
    send = Mock()
    assert not deliver_one(sessions, send)
    send.assert_not_called()
    now = func.now()
    with sessions.begin() as db:
        assert db.scalar(select(OutboxMessage.next_attempt_at > now))
        db.execute(update(OutboxMessage).values(next_attempt_at=now))
    assert deliver_one(sessions, send)
    send.assert_called_once()
    assert not deliver_one(sessions, send)
    sent, = recommendations(client)
    assert sent["notification_status"] == "sent" and sent["notification_attempts"] == 2
    assert sent["delivered_at"]


def test_permanent_error_and_expired_lease(client, stock, database):
    assert order(client, stock, "lease", 6).status_code == 201
    sessions = sessionmaker(database)
    original = claim_message(sessions)
    assert original and original.attempts == 1
    with sessions.begin() as db:
        db.execute(update(OutboxMessage).values(lease_until=func.now()))
    send = Mock(side_effect=DeliveryError("telegram_http_error", retry=False))
    assert deliver_one(sessions, send)
    assert not deliver_one(sessions, send)
    failed, = recommendations(client)
    assert failed["notification_status"] == "failed" and failed["notification_attempts"] == 2


def test_telegram_adapter_mocks_https_and_conceals_provider_error():
    with patch("app.telegram_worker.build_opener") as opener:
        opener.return_value.open.return_value = BytesIO(b'{"ok":true}')
        send = telegram_sender("123:fake_token", "-1234")
        send("test message")
        request = opener.return_value.open.call_args.args[0]
        assert request.get_method() == "POST" and request.host == "api.telegram.org"
        assert b'"chat_id": "-1234"' in request.data
        opener.return_value.open.side_effect = HTTPError(
            "https://api.telegram.org/bot123:fake_token/sendMessage", 429, "rate limit", {},
            BytesIO(b'{"parameters":{"retry_after":42}}'),
        )
        with pytest.raises(DeliveryError) as failure:
            send("test message")
        assert failure.value.delay == 42 and "fake_token" not in str(failure.value)


def test_policy_validation_and_unauthenticated_reads(client, stock):
    path = f"/replenishment/policies/{stock['product_id']}/{stock['warehouse_id']}"
    response = client.patch(path, json={"threshold": 5, "target": 5})
    assert response.status_code == 422
    response = client.get("/replenishment/recommendations", headers={"Authorization": ""})
    assert response.status_code == 401


def test_saving_policy_100_150_persists_and_queues_recommendation(client, stock, database):
    path = f"/replenishment/policies/{stock['product_id']}/{stock['warehouse_id']}"
    rule = stock | {"threshold": 100, "target": 150}
    response = client.patch(path, json={"threshold": 100, "target": 150})
    assert response.status_code == 200 and response.json() == rule
    assert client.get("/replenishment/policies").json() == [rule]
    draft, = recommendations(client)
    assert (draft["available"], draft["threshold"], draft["suggested_quantity"]) == (10, 100, 140)
    with sessionmaker(database)() as db:
        outbox = db.get(OutboxMessage, draft["id"])
        assert outbox is not None and outbox.status == "pending" and outbox.attempts == 0


def test_failed_delivery_waits_for_concurrent_recovery(client, stock, database):
    assert order(client, stock, "recover-during-send", 6).status_code == 201
    sessions = sessionmaker(database)
    sending = Event()
    fail_send = Event()
    finalizing = Event()
    worker_pid = []

    def send(_message):
        sending.set()
        assert fail_send.wait(10)
        raise DeliveryError("telegram_unavailable")

    def capture_worker_pid(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT replenishment_recommendations.resolved_at"):
            worker_pid.append(cursor.connection.info.backend_pid)
            finalizing.set()

    event.listen(database, "before_cursor_execute", capture_worker_pid)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(deliver_one, sessions, send)
            assert sending.wait(10)
            with database.begin() as recovery, database.connect() as observer:
                recovery.execute(update(Inventory).values(on_hand=11))
                fail_send.set()
                assert finalizing.wait(10)
                deadline = monotonic() + 5
                while not future.done() and monotonic() < deadline:
                    if observer.scalar(text("SELECT cardinality(pg_blocking_pids(:pid))"),
                                       {"pid": worker_pid[0]}):
                        break
                    sleep(0.01)
                else:
                    pytest.fail("Delivery finalization did not wait for the stock recovery transaction")
            assert future.result(timeout=10)
    finally:
        event.remove(database, "before_cursor_execute", capture_worker_pid)

    row, = recommendations(client)
    assert row["resolved_at"] is not None
    assert row["notification_status"] == "cancelled"
    assert row["notification_attempts"] == 1
