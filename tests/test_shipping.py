from datetime import UTC, datetime

from fastapi.testclient import TestClient
from shop_platform.events import OrderLineItem, ShipmentDispatched

from orders.handlers import subscriptions
from orders.service import OrderService
from tests.conftest import place

DISPATCHED_AT = datetime(2026, 3, 3, 14, 0, tzinfo=UTC)


def _dispatched(order: dict[str, object], **overrides: object) -> ShipmentDispatched:
    fields: dict[str, object] = {
        "shipment_id": "shp_1",
        "order_id": order["order_id"],
        "carrier": "postnl",
        "tracking_number": "3SPOST123456",
        "dispatched_at": DISPATCHED_AT,
        "lines": [
            OrderLineItem(
                line_id=line["line_id"],
                sku=line["sku"],
                quantity=line["quantity"],
                reservation_id=line["reservation_id"],
            )
            for line in order["lines"]
        ],
    }
    fields.update(overrides)
    return ShipmentDispatched(**fields)


def _handle(service: OrderService, event: ShipmentDispatched) -> None:
    [subscription] = subscriptions(service)
    subscription.handlers[ShipmentDispatched](event)


def test_dispatch_marks_order_shipped(client: TestClient, service: OrderService) -> None:
    order = place(client)
    _handle(service, _dispatched(order))

    body = client.get(f"/orders/{order['order_id']}").json()
    assert body["status"] == "shipped"
    assert body["carrier"] == "postnl"
    assert body["tracking_number"] == "3SPOST123456"
    assert body["shipped_at"].startswith("2026-03-03T14:00:00")


def test_duplicate_dispatch_event_is_ignored(client: TestClient, service: OrderService) -> None:
    order = place(client)
    event = _dispatched(order)
    _handle(service, event)
    _handle(service, event)
    assert client.get(f"/orders/{order['order_id']}").json()["status"] == "shipped"


def test_dispatch_for_cancelled_order_leaves_it_cancelled(
    client: TestClient, service: OrderService
) -> None:
    order = place(client)
    client.post(f"/orders/{order['order_id']}/cancel", json={"reason": "fraud_review"})
    _handle(service, _dispatched(order))
    assert client.get(f"/orders/{order['order_id']}").json()["status"] == "cancelled"


def test_shipped_order_cannot_be_cancelled(client: TestClient, service: OrderService) -> None:
    order = place(client)
    _handle(service, _dispatched(order))
    response = client.post(
        f"/orders/{order['order_id']}/cancel", json={"reason": "customer_request"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "order_not_cancellable"
