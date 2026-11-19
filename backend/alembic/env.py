from alembic import context
from sqlalchemy import create_engine, pool

import app.auth  # Register authentication tables with metadata.
from app.core.config import Settings
import app.replenishment  # Register replenishment tables with metadata.
from app.models import Base

config = context.config
metadata = Base.metadata


def migrate(connection):
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        dialect_name="postgresql", target_metadata=metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
elif (connection := config.attributes.get("connection")) is not None:
    migrate(connection)
else:
    engine = create_engine(
        Settings().database_url.get_secret_value(), poolclass=pool.NullPool
    )
    with engine.connect() as connection:
        migrate(connection)
