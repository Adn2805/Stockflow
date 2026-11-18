from contextlib import asynccontextmanager
from logging import getLogger

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.api import auth, inventory, orders, products, reports
from app.api.dependencies import Database
from app.core.config import Settings, configured_origins

logger = getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings if settings is not None else Settings()
        app.state.engine = create_engine(
            app.state.settings.database_url.get_secret_value(),
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"connect_timeout": 5},
        )
        try:
            yield
        finally:
            app.state.engine.dispose()

    app = FastAPI(
        title="StockFlow", version="0.1.0", lifespan=lifespan, max_body_size=32 * 1024
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins if settings is not None else configured_origins(),
        allow_methods=["GET", "POST", "PATCH"], allow_headers=["Authorization", "Idempotency-Key"],
    )
    app.include_router(auth.router)
    app.include_router(reports.router)
    app.include_router(products.router)
    app.include_router(inventory.router)
    app.include_router(orders.router)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError):
        issues = [
            {"location": issue["loc"], "message": issue["msg"]}
            for issue in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": "Invalid request", "issues": issues})

    @app.exception_handler(SQLAlchemyError)
    async def database_error(_: Request, exc: SQLAlchemyError):
        logger.error("Database operation failed (%s)", type(exc).__name__)
        if isinstance(exc, OperationalError):
            return JSONResponse(status_code=503, content={"detail": "Database unavailable"})
        return JSONResponse(status_code=500, content={"detail": "Database operation failed"})

    @app.get("/health", tags=["health"])
    def health(db: Database):
        try:
            db.execute(text("SELECT 1"))
        except SQLAlchemyError:
            raise HTTPException(503, "Database unavailable") from None
        return {"status": "ok"}

    return app


app = create_app()
