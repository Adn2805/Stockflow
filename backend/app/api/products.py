from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.dependencies import Database, Page, require_admin
from app.models import Product
from app.schemas import Identifier, ProductCreate, ProductPatch, ProductRead
from app.services.products import DuplicateSku, ProductNotFound, save_product

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductRead])
def list_products(db: Database, page: Page):
    return db.scalars(select(Product).order_by(Product.id).offset(page.offset).limit(page.limit)).all()


@router.post("", status_code=201, response_model=ProductRead, dependencies=[Depends(require_admin)])
def create_product(data: ProductCreate, db: Database):
    try:
        return save_product(db, data)
    except DuplicateSku:
        raise HTTPException(409, "SKU already exists") from None


@router.get("/{product_id}", response_model=ProductRead)
def get_product(product_id: Identifier, db: Database):
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "Product not found")
    return product


@router.patch("/{product_id}", response_model=ProductRead, dependencies=[Depends(require_admin)])
def patch_product(product_id: Identifier, data: ProductPatch, db: Database):
    try:
        return save_product(db, data, product_id)
    except DuplicateSku:
        raise HTTPException(409, "SKU already exists") from None
    except ProductNotFound:
        raise HTTPException(404, "Product not found") from None
