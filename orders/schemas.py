from datetime import datetime

from pydantic import BaseModel, Field
from shop_platform.clients import PaymentMethod
from shop_platform.events import CancelReason, ShippingAddress

from orders.domain import Order, PaymentOutcome


class PlaceOrderLine(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(gt=0, le=100)
    unit_price_cents: int = Field(ge=0)
    reservation_id: str = Field(min_length=1)


class PlaceOrderRequest(BaseModel):
    customer_id: str = Field(min_length=1)
    payment_method: PaymentMethod
    payment_reference: str = Field(min_length=1, max_length=100)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    lines: list[PlaceOrderLine] = Field(min_length=1, max_length=50)
    subtotal_cents: int = Field(ge=0)
    discount_cents: int = Field(ge=0)
    shipping_cents: int = Field(ge=0)
    tax_cents: int = Field(ge=0)
    total_cents: int = Field(ge=0)
    shipping_address: ShippingAddress


class CancelRequest(BaseModel):
    reason: CancelReason


class BankTransferNotification(BaseModel):
    bank_transaction_id: str = Field(min_length=1, max_length=100)
    reference: str = Field(min_length=1, max_length=100)
    amount_cents: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    received_at: datetime


class PaymentResponse(BaseModel):
    payment_id: str
    order_id: str
    outcome: PaymentOutcome
    amount_paid_cents: int


class OrderLineResponse(BaseModel):
    line_id: str
    sku: str
    name: str
    quantity: int
    unit_price_cents: int
    reservation_id: str


class OrderResponse(BaseModel):
    order_id: str
    customer_id: str
    status: str
    payment_method: PaymentMethod
    payment_reference: str
    currency: str
    lines: list[OrderLineResponse]
    subtotal_cents: int
    discount_cents: int
    shipping_cents: int
    tax_cents: int
    total_cents: int
    amount_paid_cents: int
    shipping_address: ShippingAddress
    placed_at: datetime
    confirmed_at: datetime | None
    shipped_at: datetime | None
    carrier: str | None
    tracking_number: str | None
    cancelled_at: datetime | None
    cancel_reason: CancelReason | None

    @classmethod
    def of(cls, order: Order) -> "OrderResponse":
        totals = order.totals
        return cls(
            order_id=order.order_id,
            customer_id=order.customer_id,
            status=order.status,
            payment_method=order.payment_method,
            payment_reference=order.payment_reference,
            currency=order.currency,
            lines=[
                OrderLineResponse(
                    line_id=line.line_id,
                    sku=line.sku,
                    name=line.name,
                    quantity=line.quantity,
                    unit_price_cents=line.unit_price_cents,
                    reservation_id=line.reservation_id,
                )
                for line in order.lines
            ],
            subtotal_cents=totals.subtotal_cents,
            discount_cents=totals.discount_cents,
            shipping_cents=totals.shipping_cents,
            tax_cents=totals.tax_cents,
            total_cents=totals.total_cents,
            amount_paid_cents=order.amount_paid_cents,
            shipping_address=order.shipping_address,
            placed_at=order.placed_at,
            confirmed_at=order.confirmed_at,
            shipped_at=order.shipped_at,
            carrier=order.carrier,
            tracking_number=order.tracking_number,
            cancelled_at=order.cancelled_at,
            cancel_reason=order.cancel_reason,
        )


class OrderListResponse(BaseModel):
    orders: list[OrderResponse]
