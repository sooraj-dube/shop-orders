from shop_platform.events import WAREHOUSE_STREAM, ShipmentDispatched
from shop_platform.messaging import Subscription

from orders.service import OrderService


def subscriptions(service: OrderService) -> list[Subscription]:
    return [Subscription(WAREHOUSE_STREAM, {ShipmentDispatched: service.mark_shipped})]
