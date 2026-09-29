from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from shop_platform.clock import FixedClock
from shop_platform.db import Database
from shop_platform.messaging import InMemoryPublisher

from orders.app import create_app
from orders.repository import OrderRepository
from orders.service import OrderService
from tests.fakes import FakeInventory

MIGRATIONS = Path(__file__).parent.parent / "orders" / "migrations"
START = datetime(2026, 3, 2, 9, 30, tzinfo=UTC)

ADDRESS = {
    "name": "Mara Janssen",
    "line1": "Prinsengracht 263",
    "city": "Amsterdam",
    "postal_code": "1016 GV",
    "country": "NL",
}


def order_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "customer_id": "cus_1",
        "payment_method": "card",
        "payment_reference": "pay_1",
        "currency": "EUR",
        "lines": [
            {
                "sku": "MUG-BLUE",
                "name": "Blue mug",
                "quantity": 2,
                "unit_price_cents": 1250,
                "reservation_id": "res_1",
            },
            {
                "sku": "TEA-50",
                "name": "Loose leaf tea",
                "quantity": 1,
                "unit_price_cents": 900,
                "reservation_id": "res_2",
            },
        ],
        "subtotal_cents": 3400,
        "discount_cents": 0,
        "shipping_cents": 495,
        "tax_cents": 818,
        "total_cents": 4713,
        "shipping_address": ADDRESS,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(START)


@pytest.fixture
def publisher() -> InMemoryPublisher:
    return InMemoryPublisher()


@pytest.fixture
def inventory() -> FakeInventory:
    return FakeInventory()


@pytest.fixture
def service(
    clock: FixedClock, publisher: InMemoryPublisher, inventory: FakeInventory
) -> OrderService:
    db = Database(":memory:")
    db.migrate(MIGRATIONS)
    return OrderService(
        repo=OrderRepository(db),
        publisher=publisher,
        inventory=inventory,
        clock=clock,
        payment_window=timedelta(hours=72),
    )


@pytest.fixture
def client(service: OrderService) -> TestClient:
    return TestClient(create_app(service))


def place(client: TestClient, key: str = "chk_0001", **overrides: object) -> dict[str, object]:
    response = client.post(
        "/orders", json=order_payload(**overrides), headers={"Idempotency-Key": key}
    )
    assert response.status_code == 201, response.text
    return response.json()
