from fastapi.testclient import TestClient
from shop_platform.events import OrderConfirmed
from shop_platform.messaging import InMemoryPublisher

from tests.conftest import place

REFERENCE = "SHOP-7Q4K2M9X"


def _bank_order(client: TestClient) -> dict[str, object]:
    return place(client, payment_method="bank_transfer", payment_reference=REFERENCE)


def _transfer(client: TestClient, amount: int, txn: str = "txn_1", **overrides: object):
    body = {
        "bank_transaction_id": txn,
        "reference": REFERENCE,
        "amount_cents": amount,
        "currency": "EUR",
        "received_at": "2026-03-03T08:00:00Z",
    }
    body.update(overrides)
    return client.post("/payments/bank-transfers", json=body)


def test_full_payment_confirms_and_announces_order(
    client: TestClient, publisher: InMemoryPublisher
) -> None:
    order = _bank_order(client)
    response = _transfer(client, 4713)

    assert response.status_code == 200
    assert response.json()["outcome"] == "confirmed"
    body = client.get(f"/orders/{order['order_id']}").json()
    assert body["status"] == "confirmed"
    assert body["amount_paid_cents"] == 4713
    [event] = publisher.of_type(OrderConfirmed)
    assert event.order_id == order["order_id"]


def test_two_partial_payments_confirm_once_the_total_is_reached(
    client: TestClient, publisher: InMemoryPublisher
) -> None:
    _bank_order(client)
    first = _transfer(client, 3000, txn="txn_1").json()
    second = _transfer(client, 1713, txn="txn_2").json()

    assert first["outcome"] == "partially_paid"
    assert first["amount_paid_cents"] == 3000
    assert second["outcome"] == "confirmed"
    assert len(publisher.of_type(OrderConfirmed)) == 1


def test_repeated_bank_notification_is_counted_once(client: TestClient) -> None:
    order = _bank_order(client)
    _transfer(client, 3000)
    again = _transfer(client, 3000).json()

    assert again["outcome"] == "duplicate"
    assert client.get(f"/orders/{order['order_id']}").json()["amount_paid_cents"] == 3000


def test_payment_for_cancelled_order_needs_refund(
    client: TestClient, publisher: InMemoryPublisher
) -> None:
    order = _bank_order(client)
    client.post(f"/orders/{order['order_id']}/cancel", json={"reason": "customer_request"})
    response = _transfer(client, 4713).json()

    assert response["outcome"] == "needs_refund"
    assert client.get(f"/orders/{order['order_id']}").json()["status"] == "cancelled"
    assert publisher.of_type(OrderConfirmed) == []


def test_unknown_reference_is_404(client: TestClient) -> None:
    response = _transfer(client, 100, reference="SHOP-NOPE0000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_payment_reference"


def test_card_order_reference_does_not_accept_transfers(client: TestClient) -> None:
    place(client, payment_reference="pay_card_1")
    assert _transfer(client, 100, reference="pay_card_1").status_code == 404


def test_wrong_currency_is_rejected(client: TestClient) -> None:
    _bank_order(client)
    response = _transfer(client, 4713, currency="USD")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "currency_mismatch"
