import os
import socket
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_path: str = "orders.db"
    redis_url: str = "redis://localhost:6379/0"
    inventory_url: str = "http://localhost:8001"
    payment_window_hours: int = 72
    expiry_interval_seconds: int = 300
    consumer_name: str = "orders"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_path=os.environ.get("ORDERS_DATABASE_PATH", cls.database_path),
            redis_url=os.environ.get("REDIS_URL", cls.redis_url),
            inventory_url=os.environ.get("INVENTORY_URL", cls.inventory_url),
            payment_window_hours=int(
                os.environ.get("PAYMENT_WINDOW_HOURS", cls.payment_window_hours)
            ),
            expiry_interval_seconds=int(
                os.environ.get("ORDER_EXPIRY_INTERVAL_SECONDS", cls.expiry_interval_seconds)
            ),
            consumer_name=os.environ.get("CONSUMER_NAME", socket.gethostname()),
            log_level=os.environ.get("LOG_LEVEL", cls.log_level),
        )
