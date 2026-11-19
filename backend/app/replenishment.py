from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, ForeignKeyConstraint, Identity, Index, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class ReorderPolicy(Base):
    __tablename__ = "reorder_policies"
    __table_args__ = (
        ForeignKeyConstraint(["product_id", "warehouse_id"], ["inventory.product_id", "inventory.warehouse_id"]),
    )

    product_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    threshold: Mapped[int] = mapped_column(BigInteger)
    target: Mapped[int] = mapped_column(BigInteger)


class Recommendation(Base):
    __tablename__ = "replenishment_recommendations"
    __table_args__ = (
        ForeignKeyConstraint(["product_id", "warehouse_id"], ["reorder_policies.product_id", "reorder_policies.warehouse_id"]),
        Index("uq_replenishment_active", "product_id", "warehouse_id", unique=True,
              postgresql_where=text("resolved_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    product_id: Mapped[int] = mapped_column(BigInteger)
    warehouse_id: Mapped[int] = mapped_column(BigInteger)
    available: Mapped[int] = mapped_column(BigInteger)
    threshold: Mapped[int] = mapped_column(BigInteger)
    suggested_quantity: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxMessage(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (
        Index("ix_notification_ready", "next_attempt_at", postgresql_where=text("status IN ('pending', 'retry')")),
        Index("ix_notification_lease", "lease_until", postgresql_where=text("status = 'sending'")),
    )

    recommendation_id: Mapped[int] = mapped_column(ForeignKey("replenishment_recommendations.id"), primary_key=True)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    attempts: Mapped[int] = mapped_column(server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    claim_token: Mapped[UUID | None] = mapped_column(Uuid)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
