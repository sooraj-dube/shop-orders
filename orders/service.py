import logging

from shop_platform.clock import Clock
from shop_platform.events import (
    ORDERS_STREAM,
    CancelReason,
    OrderCancelled,
    OrderConfirmed,
)
from shop_platform.ids import new_id
from shop_platform.messaging import EventPublisher

from orders.domain import (
    CANCELLABLE,
    DuplicatePaymentReference,
    Order,
    OrderLine,
    OrderNotCancellable,
    OrderNotFound,
    OrderStatus,
    Totals,
    check_totals,
    initial_status,
)
from orders.repository import OrderRepository
from orders.schemas import PlaceOrderRequest

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
