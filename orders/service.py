import logging

from shop_platform.clients import PaymentMethod
from shop_platform.clock import Clock
from shop_platform.events import (
    ORDERS_STREAM,
    CancelReason,
    OrderCancelled,
    OrderConfirmed,
    ShipmentDispatched,
)
from shop_platform.ids import new_id
from shop_platform.messaging import EventPublisher

from orders.domain import (
    CANCELLABLE,
    CurrencyMismatch,
    DuplicatePaymentReference,
    Order,
    OrderLine,
    OrderNotCancellable,
    OrderNotFound,
    OrderStatus,
    PaymentOutcome,
    PaymentResult,
    Totals,
    UnknownPaymentReference,
    check_totals,
    initial_status,
)
from orders.repository import OrderRepository
from orders.schemas import BankTransferNotification, PlaceOrderRequest

logger = logging.getLogger(__name__)


class OrderService:
    def __init__(self, repo: OrderRepository, publisher: EventPublisher, clock: Clock) -> None:
        self.repo = repo
        self.publisher = publisher
        self.clock = clock

    def place_order(self, request: PlaceOrderRequest, idempotency_key: str) -> tuple[Order, bool]:
        """Create an order. Returns the order and whether it was created by this call."""
        existing_id = self.repo.order_id_for_key(idempotency_key)
        if existing_id is not None:
            return self.get_order(existing_id), False

        lines = [
            OrderLine(
                line_id=new_id("lin"),
                sku=line.sku,
                name=line.name,
                quantity=line.quantity,
                unit_price_cents=line.unit_price_cents,
                reservation_id=line.reservation_id,
            )
            for line in request.lines
        ]
        totals = Totals(
            subtotal_cents=request.subtotal_cents,
            discount_cents=request.discount_cents,
            shipping_cents=request.shipping_cents,
            tax_cents=request.tax_cents,
            total_cents=request.total_cents,
        )
        check_totals(lines, totals)
        if self.repo.payment_reference_taken(request.payment_reference):
            raise DuplicatePaymentReference(
                f"payment reference {request.payment_reference} is already used"
            )

        now = self.clock.now()
        status = initial_status(request.payment_method)
        order = Order(
            order_id=new_id("ord"),
            customer_id=request.customer_id,
            status=status,
            payment_method=request.payment_method,
            payment_reference=request.payment_reference,
            currency=request.currency,
            lines=lines,
            totals=totals,
            shipping_address=request.shipping_address,
            placed_at=now,
            confirmed_at=now if status is OrderStatus.CONFIRMED else None,
        )
        self.repo.insert(order, idempotency_key)
        logger.info(
            "order placed",
            extra={"order_id": order.order_id, "status": status, "total": totals.total_cents},
        )
        if status is OrderStatus.CONFIRMED:
            self._publish_confirmed(order)
        return order, True

    def get_order(self, order_id: str) -> Order:
        order = self.repo.get(order_id)
        if order is None:
            raise OrderNotFound(f"order {order_id} not found")
        return order

    def list_orders(self, customer_id: str, limit: int = 20) -> list[Order]:
        return self.repo.list_for_customer(customer_id, limit)

    def cancel_order(self, order_id: str, reason: CancelReason) -> Order:
        order = self.get_order(order_id)
        if order.status is OrderStatus.CANCELLED:
            return order
        now = self.clock.now()
        cancelled = self.repo.transition(
            order_id,
            CANCELLABLE,
            OrderStatus.CANCELLED,
            now,
            cancelled_at=now,
            cancel_reason=reason,
        )
        if not cancelled:
            current = self.get_order(order_id)
            logger.warning(
                "cancel refused",
                extra={"order_id": order_id, "status": current.status},
            )
            raise OrderNotCancellable(f"order {order_id} is {current.status}")
        self.publisher.publish(
            ORDERS_STREAM,
            OrderCancelled(order_id=order_id, reason=reason, lines=order.event_lines()),
        )
        logger.info("order cancelled", extra={"order_id": order_id, "reason": reason})
        return self.get_order(order_id)

    def record_bank_transfer(self, payment: BankTransferNotification) -> PaymentResult:
        """Record an incoming bank transfer and confirm the order once it is paid in full.

        A transfer for an order that is no longer awaiting payment is still recorded, and
        reported as ``needs_refund`` so the money can be sent back.
        """
        seen = self.repo.payment_for_transaction(payment.bank_transaction_id)
        if seen is not None:
            payment_id, order_id = seen
            paid = self.get_order(order_id).amount_paid_cents
            return PaymentResult(payment_id, order_id, PaymentOutcome.DUPLICATE, paid)

        order = self.repo.find_by_payment_reference(payment.reference)
        if order is None or order.payment_method is not PaymentMethod.BANK_TRANSFER:
            logger.warning("bank transfer with unknown reference", extra={"ref": payment.reference})
            raise UnknownPaymentReference(f"no bank-transfer order for {payment.reference}")
        if payment.currency != order.currency:
            logger.warning(
                "bank transfer in wrong currency",
                extra={"order_id": order.order_id, "currency": payment.currency},
            )
            raise CurrencyMismatch(f"order is in {order.currency}, payment in {payment.currency}")

        now = self.clock.now()
        payment_id = new_id("pay")
        with self.repo.db.transaction():
            self.repo.record_payment(
                payment_id=payment_id,
                order_id=order.order_id,
                bank_transaction_id=payment.bank_transaction_id,
                amount_cents=payment.amount_cents,
                currency=payment.currency,
                received_at=payment.received_at,
                recorded_at=now,
            )
            current = self.get_order(order.order_id)
            if current.status is not OrderStatus.AWAITING_PAYMENT:
                outcome = PaymentOutcome.NEEDS_REFUND
            elif current.amount_paid_cents < current.totals.total_cents:
                outcome = PaymentOutcome.PARTIALLY_PAID
            elif self.repo.transition(
                order.order_id,
                [OrderStatus.AWAITING_PAYMENT],
                OrderStatus.CONFIRMED,
                now,
                confirmed_at=now,
            ):
                outcome = PaymentOutcome.CONFIRMED
            else:
                outcome = PaymentOutcome.NEEDS_REFUND

        if outcome is PaymentOutcome.NEEDS_REFUND:
            logger.warning(
                "payment received for order not awaiting payment",
                extra={"order_id": order.order_id, "status": current.status},
            )
        if outcome is PaymentOutcome.CONFIRMED:
            self._publish_confirmed(self.get_order(order.order_id))
        logger.info(
            "bank transfer recorded",
            extra={"order_id": order.order_id, "payment_id": payment_id, "outcome": outcome},
        )
        return PaymentResult(payment_id, order.order_id, outcome, current.amount_paid_cents)

    def mark_shipped(self, event: ShipmentDispatched) -> None:
        with self.repo.db.transaction():
            if not self.repo.mark_event_processed(
                event.event_id, event.EVENT_TYPE, self.clock.now()
            ):
                return
            shipped = self.repo.transition(
                event.order_id,
                [OrderStatus.CONFIRMED],
                OrderStatus.SHIPPED,
                self.clock.now(),
                shipped_at=event.dispatched_at,
                carrier=event.carrier,
                tracking_number=event.tracking_number,
            )
        if not shipped:
            order = self.repo.get(event.order_id)
            logger.warning(
                "dispatch for order not awaiting shipment",
                extra={
                    "order_id": event.order_id,
                    "status": order.status if order else None,
                    "shipment_id": event.shipment_id,
                },
            )
            return
        logger.info(
            "order shipped",
            extra={"order_id": event.order_id, "shipment_id": event.shipment_id},
        )

    def _publish_confirmed(self, order: Order) -> None:
        self.publisher.publish(
            ORDERS_STREAM,
            OrderConfirmed(
                order_id=order.order_id,
                customer_id=order.customer_id,
                lines=order.event_lines(),
                shipping_address=order.shipping_address,
            ),
        )
