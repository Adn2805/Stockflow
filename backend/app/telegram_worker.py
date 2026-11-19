"""Deliver committed Telegram messages. Run separately from the web server."""

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
import json
from logging import getLogger
import re
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID, uuid4

from sqlalchemy import and_, create_engine, exists, func, or_, select, update
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.models import Product, Warehouse
from app.replenishment import OutboxMessage, Recommendation

MAX_ATTEMPTS = 5
LEASE = timedelta(minutes=2)
logger = getLogger(__name__)


class DeliveryError(Exception):
    def __init__(self, code: str, *, retry: bool = True, delay: int = 0):
        super().__init__(code)
        self.code = code
        self.retry = retry
        self.delay = delay


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def telegram_sender(token: str, chat_id: str) -> Callable[[str], None]:
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token) or not re.fullmatch(r"-?[0-9]+", chat_id):
        raise ValueError("Telegram token or numeric chat ID format is invalid")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    opener = build_opener(ProxyHandler({}), NoRedirect())

    def send(message: str):
        request = Request(url, data=json.dumps({"chat_id": chat_id, "text": message}).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with opener.open(request, timeout=10) as response:
                result = json.load(response)
        except HTTPError as exc:
            if exc.code == 429:
                try:
                    delay = int(json.load(exc).get("parameters", {}).get("retry_after", 0))
                except (TypeError, ValueError, AttributeError, OSError):
                    delay = 0
                raise DeliveryError("telegram_rate_limit", delay=max(0, delay)) from None
            raise DeliveryError("telegram_http_error", retry=exc.code >= 500) from None
        except (URLError, OSError, ValueError):
            raise DeliveryError("telegram_unavailable") from None
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise DeliveryError("telegram_invalid_response")

    return send


@dataclass(frozen=True)
class Claim:
    recommendation_id: int
    token: UUID
    attempts: int
    text: str


def claim_message(sessions: sessionmaker) -> Claim | None:
    active = exists().where(
        Recommendation.id == OutboxMessage.recommendation_id, Recommendation.resolved_at.is_(None),
    )
    expired = and_(OutboxMessage.status == "sending", OutboxMessage.lease_until <= func.now())
    with sessions.begin() as db:
        db.execute(update(OutboxMessage).where(expired, ~active)
                   .values(status="cancelled", claim_token=None, lease_until=None))
        db.execute(update(OutboxMessage).where(expired, OutboxMessage.attempts >= MAX_ATTEMPTS)
                   .values(status="failed", claim_token=None, lease_until=None, last_error="lease_expired"))
        ready = and_(OutboxMessage.status.in_(("pending", "retry")),
                     OutboxMessage.next_attempt_at <= func.now())
        row = db.execute(
            select(OutboxMessage, Recommendation, Product.name, Warehouse.name)
            .join(Recommendation).join(Product, Product.id == Recommendation.product_id)
            .join(Warehouse, Warehouse.id == Recommendation.warehouse_id)
            .where(Recommendation.resolved_at.is_(None), or_(ready, expired))
            .order_by(OutboxMessage.next_attempt_at, OutboxMessage.recommendation_id)
            .limit(1).with_for_update(of=OutboxMessage, skip_locked=True)
        ).first()
        if row is None:
            return None
        outbox, draft, product, warehouse = row
        token = uuid4()
        outbox.status = "sending"
        outbox.attempts += 1
        outbox.claim_token = token
        outbox.lease_until = db.scalar(select(func.now())) + LEASE
        return Claim(
            draft.id, token, outbox.attempts,
            f"StockFlow low stock · recommendation #{draft.id}\n"
            f"Product: {product}\nWarehouse: {warehouse}\nAvailable: {draft.available}\n"
            f"Reorder threshold: {draft.threshold}\nSuggested reorder: {draft.suggested_quantity}\n"
            "Review the draft in StockFlow. No purchase has been made.",
        )


def deliver_one(sessions: sessionmaker, send: Callable[[str], None]) -> bool:
    claim = claim_message(sessions)
    if claim is None:
        return False
    failure = None
    try:
        send(claim.text)
    except DeliveryError as exc:
        failure = exc

    with sessions.begin() as db:
        values = {"claim_token": None, "lease_until": None, "last_error": None}
        if failure is None:
            values.update(status="sent", delivered_at=func.now())
        else:
            values["last_error"] = failure.code
            # Match the inventory trigger lock order so recovery and retry cannot cross.
            resolved = db.scalar(select(Recommendation.resolved_at)
                                 .where(Recommendation.id == claim.recommendation_id).with_for_update())
            if resolved is not None:
                values["status"] = "cancelled"
            elif not failure.retry or claim.attempts >= MAX_ATTEMPTS:
                values["status"] = "failed"
            else:
                wait = max(failure.delay, 15 * 2 ** (claim.attempts - 1))
                values.update(status="retry", next_attempt_at=func.now() + timedelta(seconds=wait))
        db.execute(update(OutboxMessage).where(
            OutboxMessage.recommendation_id == claim.recommendation_id,
            OutboxMessage.claim_token == claim.token,
        ).values(**values))
    return True


def database_error_message(error: OperationalError, engine: Engine) -> str:
    state = getattr(error.orig, "sqlstate", None)
    if state == "3D000":
        return "configured PostgreSQL database does not exist"
    if state == "28P01":
        return "PostgreSQL rejected the configured credentials"
    if engine.url.host in {"localhost", "127.0.0.1", "::1"}:
        return "PostgreSQL is unreachable on loopback. In Compose use the telegram-worker service"
    return "PostgreSQL is unreachable. Check the configured database address and service health"


def check_database(engine: Engine) -> None:
    with engine.connect() as db:
        db.execute(select(OutboxMessage.recommendation_id).join(Recommendation).limit(0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Process at most one due message and exit")
    parser.add_argument("--check-db", action="store_true", help="Verify outbox access without sending")
    args = parser.parse_args()
    settings = Settings()
    if not args.check_db and (settings.public_demo or not settings.telegram_bot_token or not settings.telegram_chat_id):
        parser.error("Use a private instance and set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
    engine = create_engine(
        make_url(settings.database_url.get_secret_value()), pool_pre_ping=True,
        hide_parameters=True, connect_args={"connect_timeout": 5},
    )
    try:
        if args.check_db:
            try:
                check_database(engine)
            except OperationalError as exc:
                parser.exit(1, f"Outbox database check failed: {database_error_message(exc, engine)}.\n")
            except SQLAlchemyError:
                parser.exit(1, "Outbox database check failed. Verify migration 0004 and table permissions.\n")
            print("PostgreSQL connection and outbox table access verified.")
            return
        try:
            send = telegram_sender(settings.telegram_bot_token.get_secret_value(),
                                   settings.telegram_chat_id.get_secret_value())
        except ValueError:
            parser.error("Telegram token or numeric chat ID format is invalid")
        sessions = sessionmaker(engine)
        while True:
            try:
                processed = deliver_one(sessions, send)
            except OperationalError as exc:
                logger.error("Outbox database connection failed: %s", database_error_message(exc, engine))
                if args.once:
                    raise SystemExit(1) from None
                processed = False
            except Exception as exc:
                logger.error("Outbox worker error (%s)", type(exc).__name__)
                if args.once:
                    raise SystemExit(1) from None
                processed = False
            if args.once:
                return
            sleep(1.1 if processed else 5)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
