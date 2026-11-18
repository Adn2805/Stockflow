import os
from pathlib import Path
from secrets import token_hex
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import Settings
from app.main import create_app
from app.models import Warehouse


@pytest.fixture
def database():
    raw_url = os.getenv("TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    url = make_url(raw_url)
    if url.drivername != "postgresql+psycopg" or not (url.database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must use psycopg and a database ending in _test")

    schema = f"stockflow_test_{uuid4().hex}"
    admin = create_engine(url)
    test_url = url.update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(test_url)
    try:
        with admin.begin() as connection:
            connection.execute(CreateSchema(schema))
        with engine.connect() as connection:
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()
        try:
            with admin.begin() as connection:
                connection.execute(DropSchema(schema, if_exists=True, cascade=True))
        finally:
            admin.dispose()


@pytest.fixture
def client(database):
    token = token_hex(32)
    settings = Settings(
        database_url=database.url.render_as_string(hide_password=False), write_token=token
    )
    with TestClient(create_app(settings)) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        yield client


@pytest.fixture
def warehouse(database):
    with Session(database, expire_on_commit=False) as session, session.begin():
        warehouse = Warehouse(name="Central", location="Test site")
        session.add(warehouse)
    return warehouse
