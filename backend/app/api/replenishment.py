from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.api.dependencies import Credentials, Database, Page, get_principal, require_admin
from app.models import Inventory, Product, Warehouse
from app.replenishment import OutboxMessage, Recommendation, ReorderPolicy
from app.schemas import Identifier, MAX_BIGINT

def require_replenishment_admin(request: Request, credentials: Credentials) -> None:
    if request.app.state.settings.public_demo:
        raise HTTPException(403, "Replenishment is available only in the private instance")
    require_admin(get_principal(request, credentials))


router = APIRouter(
    prefix="/replenishment", tags=["replenishment"], dependencies=[Depends(require_replenishment_admin)]
)


class PolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    threshold: Annotated[int, Field(strict=True, ge=0, le=MAX_BIGINT - 1)]
    target: Annotated[int, Field(strict=True, gt=0, le=MAX_BIGINT)]

    @model_validator(mode="after")
    def validate_target(self):
        if self.target <= self.threshold:
            raise ValueError("Target must be greater than the threshold")
        return self


class PolicyRead(PolicyInput):
    model_config = ConfigDict(from_attributes=True)
    product_id: int
    warehouse_id: int


class RecommendationRead(BaseModel):
    id: int
    product_id: int
    warehouse_id: int
    available: int
    threshold: int
    suggested_quantity: int
    created_at: datetime
    approved_at: datetime | None
    resolved_at: datetime | None
    notification_status: str
    notification_attempts: int
    delivered_at: datetime | None


@router.get("/policies", response_model=list[PolicyRead])
def list_policies(db: Database, page: Page):
    return db.scalars(select(ReorderPolicy).order_by(ReorderPolicy.product_id, ReorderPolicy.warehouse_id)
                      .limit(page.limit).offset(page.offset)).all()


@router.patch("/policies/{product_id}/{warehouse_id}", response_model=PolicyRead)
def configure_policy(product_id: Identifier, warehouse_id: Identifier, data: PolicyInput, db: Database):
    key = {"product_id": product_id, "warehouse_id": warehouse_id}
    with db.begin():
        if db.get(Product, product_id) is None or db.get(Warehouse, warehouse_id) is None:
            raise HTTPException(404, "Product or warehouse not found")
        db.execute(insert(Inventory).values(**key).on_conflict_do_nothing())
        balance = db.get(Inventory, (product_id, warehouse_id), with_for_update=True)
        values = data.model_dump()
        policy = db.scalars(insert(ReorderPolicy).values(**key, **values)
                            .on_conflict_do_update(index_elements=["product_id", "warehouse_id"], set_=values)
                            .returning(ReorderPolicy)).one()
        db.execute(text("SELECT evaluate_replenishment(:product_id, :warehouse_id, :available)"),
                   key | {"available": balance.available})
    return policy


@router.get("/recommendations", response_model=list[RecommendationRead])
def list_recommendations(db: Database, page: Page, active_only: bool = False):
    statement = select(
        *Recommendation.__table__.c,
        OutboxMessage.status.label("notification_status"),
        OutboxMessage.attempts.label("notification_attempts"),
        OutboxMessage.delivered_at,
    ).join(OutboxMessage)
    if active_only:
        statement = statement.where(Recommendation.resolved_at.is_(None))
    return db.execute(statement.order_by(Recommendation.id.desc())
                      .limit(page.limit).offset(page.offset)).mappings().all()


@router.post("/recommendations/{recommendation_id}/approve")
def approve(recommendation_id: Identifier, db: Database):
    with db.begin():
        row = db.get(Recommendation, recommendation_id, with_for_update=True)
        if row is None:
            raise HTTPException(404, "Recommendation not found")
        if row.resolved_at is not None:
            raise HTTPException(409, "Stock has recovered")
        if row.approved_at is None:
            approved_at = db.scalar(update(Recommendation).where(Recommendation.id == row.id)
                                    .values(approved_at=func.now()).returning(Recommendation.approved_at))
        else:
            approved_at = row.approved_at
    return {"id": recommendation_id, "approved_at": approved_at}
