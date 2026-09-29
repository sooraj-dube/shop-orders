from fastapi.testclient import TestClient
from shop_platform.events import OrderCancelled, OrderConfirmed
from shop_platform.messaging import InMemoryPublisher

from tests.conftest import order_payload, place


def test_card_order_is_confirmed_and_announced(
    client: TestClient, publisher: InMemoryPublisher
) -> None:
    order = place(client)

    assert order["status"] == "confirmed"
    assert order["confirmed_at"] is not None
    assert [line["reservation_id"] for line in order["lines"]] == ["res_1", "res_2"]
    [event] = publisher.of_type(OrderConfirmed)
    assert event.order_id == order["order_id"]
    assert [line.sku for line in event.lines] == ["MUG-BLUE", "TEA-50"]


def test_bank_transfer_order_waits_for_payment(
    client: TestClient, publisher: InMemoryPublisher
) -> None:
    order = place(client, payment_method="bank_transfer", payment_reference="SHOP-7Q4K2M9X")

    assert order["status"] == "awaiting_payment"
    assert order["confirmed_at"] is None
    assert publisher.events() == []


def test_repeated_request_returns_the_same_order(client: TestClient) -> None:
    first = place(client, key="chk_0042")
    again = client.post("/orders", json=order_payload(), headers={"Idempotency-Key": "chk_0042"})

    assert again.status_code == 200
    assert again.json()["order_id"] == first["order_id"]


def test_totals_that_do_not_add_up_are_rejected(client: TestClient) -> None:
    response = client.post(
        "/orders",
        json=order_payload(total_cents=4000),
        headers={"Idempotency-Key": "chk_bad_total"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_order"


def test_payment_reference_cannot_be_reused(client: TestClient) -> None:
    place(client, key="chk_aaaa")
    response = client.post("/orders", json=order_payload(), headers={"Idempotency-Key": "chk_bbbb"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate_payment_reference"


def test_idempotency_key_is_required(client: TestClient) -> None:
    assert client.post("/orders", json=order_payload()).status_code == 422


def test_unknown_order_is_404(client: TestClient) -> None:
    response = client.get("/orders/ord_missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "order_not_found"


def test_customer_orders_are_newest_first(client: TestClient, clock) -> None:
    first = place(client, key="chk_0001", payment_reference="pay_1")
    clock.advance(hours=1)
    second = place(client, key="chk_0002", payment_reference="pay_2")

    body = client.get("/customers/cus_1/orders").json()
    assert [o["order_id"] for o in body["orders"]] == [second["order_id"], first["order_id"]]


def test_cancel_publishes_lines_with_reservations(
    client: TestClient, publisher: InMemoryPublisher
) -> None:
    order = place(client)
    response = client.post(
        f"/orders/{order['order_id']}/cancel", json={"reason": "customer_request"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    [event] = publisher.of_type(OrderCancelled)
    assert {line.reservation_id for line in event.lines} == {"res_1", "res_2"}


def test_cancel_twice_publishes_once(client: TestClient, publisher: InMemoryPublisher) -> None:
    order = place(client)
    for _ in range(2):
        client.post(f"/orders/{order['order_id']}/cancel", json={"reason": "customer_request"})
    assert len(publisher.of_type(OrderCancelled)) == 1
