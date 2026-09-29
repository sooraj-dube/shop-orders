from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from shop_platform.clients import PaymentMethod
from shop_platform.events import CancelReason, OrderLineItem, ShippingAddress


class OrderStatus(StrEnum):
    AWAITING_PAYMENT = "awaiting_payment"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    CANCELLED = "cancelled"


CANCELLABLE = frozenset({OrderStatus.AWAITING_PAYMENT, OrderStatus.CONFIRMED})


class PaymentOutcome(StrEnum):
    CONFIRMED = "confirmed"
    PARTIALLY_PAID = "partially_paid"
    NEEDS_REFUND = "needs_refund"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class PaymentResult:
    payment_id: str
    order_id: str
    outcome: PaymentOutcome
    amount_paid_cents: int


@dataclass(frozen=True)
class OrderLine:
    line_id: str
    sku: str
    name: str
    quantity: int
    unit_price_cents: int
    reservation_id: str

    @property
    def total_cents(self) -> int:
        return self.quantity * self.unit_price_cents

    def as_event_line(self) -> OrderLineItem:
        return OrderLineItem(
            line_id=self.line_id,
            sku=self.sku,
            quantity=self.quantity,
            reservation_id=self.reservation_id,
        )


@dataclass(frozen=True)
class Totals:
    subtotal_cents: int
    discount_cents: int
    shipping_cents: int
    tax_cents: int
    total_cents: int


@dataclass(frozen=True)
class Order:
    order_id: str
    customer_id: str
    status: OrderStatus
    payment_method: PaymentMethod
    payment_reference: str
    currency: str
    lines: list[OrderLine]
    totals: Totals
    shipping_address: ShippingAddress
    placed_at: datetime
    confirmed_at: datetime | None = None
    shipped_at: datetime | None = None
    carrier: str | None = None
    tracking_number: str | None = None
    cancelled_at: datetime | None = None
    cancel_reason: CancelReason | None = None
    amount_paid_cents: int = field(default=0)

    def event_lines(self) -> list[OrderLineItem]:
        return [line.as_event_line() for line in self.lines]


class OrderError(Exception):
    code = "order_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class OrderNotFound(OrderError):
    code = "order_not_found"


class InvalidOrder(OrderError):
    code = "invalid_order"


class DuplicatePaymentReference(OrderError):
    code = "duplicate_payment_reference"


class OrderNotCancellable(OrderError):
    code = "order_not_cancellable"


class UnknownPaymentReference(OrderError):
    code = "unknown_payment_reference"


class CurrencyMismatch(OrderError):
    code = "currency_mismatch"


def check_totals(lines: list[OrderLine], totals: Totals) -> None:
    """Reject orders whose totals do not add up."""
    subtotal = sum(line.total_cents for line in lines)
    if subtotal != totals.subtotal_cents:
        raise InvalidOrder(f"subtotal {totals.subtotal_cents} does not match lines ({subtotal})")
    if totals.discount_cents > totals.subtotal_cents:
        raise InvalidOrder("discount is larger than the subtotal")
    expected = (
        totals.subtotal_cents - totals.discount_cents + totals.shipping_cents + totals.tax_cents
    )
    if expected != totals.total_cents:
        raise InvalidOrder(f"total {totals.total_cents} does not add up (expected {expected})")
    skus = [line.sku for line in lines]
    if len(skus) != len(set(skus)):
        raise InvalidOrder("each sku may appear on only one line")


def initial_status(payment_method: PaymentMethod) -> OrderStatus:
    if payment_method is PaymentMethod.CARD:
        return OrderStatus.CONFIRMED
    return OrderStatus.AWAITING_PAYMENT
