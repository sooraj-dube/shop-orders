import logging
import signal
import threading

from shop_platform.logging import configure_logging
from shop_platform.messaging import StreamConsumer, redis_from_url

from orders.app import build_service
from orders.config import Settings
from orders.handlers import subscriptions
from orders.service import OrderService

logger = logging.getLogger(__name__)


def expire_periodically(service: OrderService, interval: float, stop: threading.Event) -> None:
    while not stop.wait(interval):
        try:
            report = service.expire_unpaid_orders()
        except Exception:
            logger.exception("order expiry run failed")
            continue
        if report.expired or report.released or report.release_failed:
            logger.info(
                "order expiry run",
                extra={
                    "expired": report.expired,
                    "released": report.released,
                    "release_failed": report.release_failed,
                },
            )


def main() -> None:
    settings = Settings.from_env()
    configure_logging("orders-worker", settings.log_level)
    service = build_service(settings)
    consumer = StreamConsumer(
        redis_from_url(settings.redis_url),
        group="orders",
        consumer=settings.consumer_name,
        subscriptions=subscriptions(service),
    )
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    expiry = threading.Thread(
        target=expire_periodically,
        args=(service, settings.expiry_interval_seconds, stop),
        name="order-expiry",
        daemon=True,
    )
    expiry.start()
    consumer.run(stop)
    expiry.join(timeout=5)


if __name__ == "__main__":
    main()
