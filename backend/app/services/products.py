from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Product
from app.schemas import ProductCreate, ProductPatch


class DuplicateSku(Exception):
    pass


class ProductNotFound(Exception):
    pass


def save_product(
    session: Session, data: ProductCreate | ProductPatch, product_id: int | None = None
) -> Product:
    try:
        with session.begin():
            if product_id is None:
                product = Product(**data.model_dump())
                session.add(product)
            else:
                product = session.get(Product, product_id)
                if product is None:
                    raise ProductNotFound
                for field, value in data.model_dump(exclude_unset=True).items():
                    setattr(product, field, value)
            session.flush()
            session.refresh(product)
    except IntegrityError as exc:
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == "uq_products_sku":
            raise DuplicateSku from exc
        raise
    return product
