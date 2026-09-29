from datetime import UTC, datetime

from shop_platform.clients import Reservation, ReservationStatus
from shop_platform.http import ServiceUnavailable


class FakeInventory:
    """Stands in for InventoryClient. Records releases and can simulate an outage."""

    def __init__(self) -> None:
        self.releases: list[tuple[str, str]] = []
        self.unavailable = False

    def release(self, reservation_id: str, *, idempotency_key: str) -> Reservation:
        if self.unavailable:
            raise ServiceUnavailable("inventory unavailable after 3 attempt(s)")
        if (reservation_id, idempotency_key) not in self.releases:
            self.releases.append((reservation_id, idempotency_key))
        return Reservation(
            reservation_id=reservation_id,
            sku="SKU",
            quantity=1,
            status=ReservationStatus.RELEASED,
            created_at=datetime(2026, 3, 1, tzinfo=UTC),
        )

    def released_ids(self) -> list[str]:
        return [reservation_id for reservation_id, _ in self.releases]
