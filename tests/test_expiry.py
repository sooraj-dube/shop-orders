from fastapi.testclient import TestClient
from shop_platform.clock import FixedClock

from orders.service import OrderService
from tests.conftest import place
from tests.fakes import FakeInventory


def _bank_order(client: TestClient, key: str = "chk_bank_1", ref: str = "SHOP-7Q4K2M9X"):
    return place(client, key=key, payment_method="bank_transfer", payment_reference=ref)


def _pay(client: TestClient, amount: int, txn: str = "txn_1", ref: str = "SHOP-7Q4K2M9X"):
    return client.post(
        "/payments/bank-transfers",
        json={
            "bank_transaction_id": txn,
            "reference": ref,
            "amount_cents": amount,
            "currency": "EUR",
            "received_at": "2026-03-04T08:00:00Z",
        },
    ).json()


def test_unpaid_order_expires_after_the_window_and_frees_its_stock(
    client: TestClient, service: OrderService, clock: FixedClock, inventory: FakeInventory
) -> None:
    order = _bank_order(client)
    clock.advance(hours=73)

    report = service.expire_unpaid_orders()

    assert (report.expired, report.released, report.release_failed) == (1, 1, 0)
    assert inventory.released_ids() == ["res_1", "res_2"]
    body = client.get(f"/orders/{order['order_id']}").json()
    assert body["status"] == "expired"
    assert body["expired_at"] is not None


def test_order_inside_the_window_is_left_alone(
    client: TestClient, service: OrderService, clock: FixedClock, inventory: FakeInventory
) -> None:
    order = _bank_order(client)
    clock.advance(hours=71)

    assert service.expire_unpaid_orders().expired == 0
    assert inventory.releases == []
    assert client.get(f"/orders/{order['order_id']}").json()["status"] == "awaiting_payment"


def test_paid_and_card_orders_never_expire(
    client: TestClient, service: OrderService, clock: FixedClock, inventory: FakeInventory
) -> None:
    place(client, key="chk_card_1", payment_reference="pay_card_1")
    _bank_order(client)
    _pay(client, 4713)
    clock.advance(days=10)

    assert service.expire_unpaid_orders().expired == 0
    assert inventory.releases == []


def test_failed_release_is_retried_on_the_next_run(
    client: TestClient, service: OrderService, clock: FixedClock, inventory: FakeInventory
) -> None:
    _bank_order(client)
    clock.advance(hours=73)
    inventory.unavailable = True

    first = service.expire_unpaid_orders()
    assert (first.expired, first.released, first.release_failed) == (1, 0, 1)

    inventory.unavailable = False
    second = service.expire_unpaid_orders()
    assert (second.expired, second.released, second.release_failed) == (0, 1, 0)
    assert inventory.released_ids() == ["res_1", "res_2"]

    third = service.expire_unpaid_orders()
    assert (third.expired, third.released, third.release_failed) == (0, 0, 0)


def test_transfer_after_expiry_is_recorded_for_refund(
    client: TestClient, service: OrderService, clock: FixedClock
) -> None:
    order = _bank_order(client)
    clock.advance(hours=73)
    service.expire_unpaid_orders()

    assert _pay(client, 4713)["outcome"] == "needs_refund"
    assert client.get(f"/orders/{order['order_id']}").json()["status"] == "expired"


def test_partly_paid_order_still_expires(
    client: TestClient, service: OrderService, clock: FixedClock
) -> None:
    order = _bank_order(client)
    _pay(client, 2000)
    clock.advance(hours=73)

    assert service.expire_unpaid_orders().expired == 1
    body = client.get(f"/orders/{order['order_id']}").json()
    assert body["status"] == "expired"
    assert body["amount_paid_cents"] == 2000


def test_expired_order_cannot_be_cancelled(
    client: TestClient, service: OrderService, clock: FixedClock
) -> None:
    order = _bank_order(client)
    clock.advance(hours=73)
    service.expire_unpaid_orders()

    response = client.post(
        f"/orders/{order['order_id']}/cancel", json={"reason": "customer_request"}
    )
    assert response.status_code == 409
