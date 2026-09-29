import logging
import signal
import threading

from shop_platform.logging import configure_logging
from shop_platform.messaging import StreamConsumer, redis_from_url

from orders.app import build_service
from orders.config import Settings
from orders.handlers import subscriptions

logger = logging.getLogger(__name__)


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
    consumer.run(stop)


if __name__ == "__main__":
    main()
