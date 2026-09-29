from pathlib import Path

from fastapi import FastAPI
from shop_platform.clock import SystemClock
from shop_platform.db import Database
from shop_platform.logging import configure_logging
from shop_platform.messaging import RedisStreamPublisher, redis_from_url
from shop_platform.web import health_router, install_error_handlers

from orders.api import router
from orders.config import Settings
from orders.repository import OrderRepository
from orders.service import OrderService

MIGRATIONS = Path(__file__).parent / "migrations"


def build_service(settings: Settings) -> OrderService:
    db = Database(settings.database_path)
    db.migrate(MIGRATIONS)
    return OrderService(
        repo=OrderRepository(db),
        publisher=RedisStreamPublisher(redis_from_url(settings.redis_url)),
        clock=SystemClock(),
    )


def create_app(service: OrderService | None = None) -> FastAPI:
    if service is None:
        settings = Settings.from_env()
        configure_logging("orders", settings.log_level)
        service = build_service(settings)
    app = FastAPI(title="shop-orders", version="1.0.0")
    app.state.service = service
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(router)
    return app
