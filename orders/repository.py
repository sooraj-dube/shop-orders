import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime

from shop_platform.clients import PaymentMethod
from shop_platform.db import Database
from shop_platform.events import CancelReason, ShippingAddress

from orders.domain import Order, OrderLine, OrderStatus, Totals

_ORDER_COLUMNS = (
    "order_id, customer_id, status, payment_method, payment_reference, currency,"
    " subtotal_cents, discount_cents, shipping_cents, tax_cents, total_cents,"
    " shipping_address, placed_at, confirmed_at, shipped_at, carrier, tracking_number,"
    " cancelled_at, cancel_reason"
)


def _ts(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


class OrderRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def insert(self, order: Order, idempotency_key: str) -> None:
        with self.db.transaction() as conn:
            totals = order.totals
            conn.execute(
                f"INSERT INTO orders ({_ORDER_COLUMNS}, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    order.order_id,
                    order.customer_id,
                    order.status,
                    order.payment_method,
                    order.payment_reference,
                    order.currency,
                    totals.subtotal_cents,
                    totals.discount_cents,
                    totals.shipping_cents,
                    totals.tax_cents,
                    totals.total_cents,
                    order.shipping_address.model_dump_json(),
                    _ts(order.placed_at),
                    _ts(order.confirmed_at),
                    None,
                    None,
                    None,
                    None,
                    None,
                    _ts(order.placed_at),
                ),
            )
            conn.executemany(
                "INSERT INTO order_lines (line_id, order_id, position, sku, name, quantity,"
                " unit_price_cents, reservation_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        line.line_id,
                        order.order_id,
                        position,
                        line.sku,
                        line.name,
                        line.quantity,
                        line.unit_price_cents,
                        line.reservation_id,
                    )
                    for position, line in enumerate(order.lines)
                ],
            )
            conn.execute(
                "INSERT INTO idempotency_keys (key, order_id, created_at) VALUES (?, ?, ?)",
                (idempotency_key, order.order_id, _ts(order.placed_at)),
            )

    def order_id_for_key(self, idempotency_key: str) -> str | None:
        with self.db.read() as conn:
            row = conn.execute(
                "SELECT order_id FROM idempotency_keys WHERE key = ?", (idempotency_key,)
            ).fetchone()
        return row["order_id"] if row else None

    def find_by_payment_reference(self, payment_reference: str) -> Order | None:
        with self.db.read() as conn:
            row = conn.execute(
                f"SELECT {_ORDER_COLUMNS} FROM orders WHERE payment_reference = ?",
                (payment_reference,),
            ).fetchone()
            return self._load(conn, row) if row else None

    def payment_for_transaction(self, bank_transaction_id: str) -> tuple[str, str] | None:
        """``(payment_id, order_id)`` of an already recorded bank transaction."""
        with self.db.read() as conn:
            row = conn.execute(
                "SELECT payment_id, order_id FROM payments WHERE bank_transaction_id = ?",
                (bank_transaction_id,),
            ).fetchone()
        return (row["payment_id"], row["order_id"]) if row else None

    def record_payment(
        self,
        *,
        payment_id: str,
        order_id: str,
        bank_transaction_id: str,
        amount_cents: int,
        currency: str,
        received_at: datetime,
        recorded_at: datetime,
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO payments (payment_id, order_id, bank_transaction_id, amount_cents,"
                " currency, received_at, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    payment_id,
                    order_id,
                    bank_transaction_id,
                    amount_cents,
                    currency,
                    _ts(received_at),
                    _ts(recorded_at),
                ),
            )

    def payment_reference_taken(self, payment_reference: str) -> bool:
        with self.db.read() as conn:
            row = conn.execute(
                "SELECT 1 FROM orders WHERE payment_reference = ?", (payment_reference,)
            ).fetchone()
        return row is not None

    def get(self, order_id: str) -> Order | None:
        with self.db.read() as conn:
            row = conn.execute(
                f"SELECT {_ORDER_COLUMNS} FROM orders WHERE order_id = ?", (order_id,)
            ).fetchone()
            if row is None:
                return None
            return self._load(conn, row)

    def list_for_customer(self, customer_id: str, limit: int) -> list[Order]:
        with self.db.read() as conn:
            rows = conn.execute(
                f"SELECT {_ORDER_COLUMNS} FROM orders WHERE customer_id = ?"
                " ORDER BY placed_at DESC LIMIT ?",
                (customer_id, limit),
            ).fetchall()
            return [self._load(conn, row) for row in rows]

    def transition(
        self,
        order_id: str,
        allowed_from: Iterable[OrderStatus],
        to: OrderStatus,
        at: datetime,
        **columns: object,
    ) -> bool:
        """Move an order to ``to`` only if it is currently in one of ``allowed_from``.

        Returns False when the order was in another status, so two concurrent requests
        cannot both apply a transition.
        """
        allowed = list(allowed_from)
        assignments = ", ".join(f"{name} = ?" for name in columns)
        sql = (
            f"UPDATE orders SET status = ?, updated_at = ?{', ' if columns else ''}{assignments}"
            f" WHERE order_id = ? AND status IN ({', '.join('?' for _ in allowed)})"
        )
        values = [_ts(v) if isinstance(v, datetime) else v for v in columns.values()]
        with self.db.transaction() as conn:
            cursor = conn.execute(sql, (to, _ts(at), *values, order_id, *allowed))
        return cursor.rowcount == 1

    def _load(self, conn: sqlite3.Connection, row: sqlite3.Row) -> Order:
        lines = [
            OrderLine(
                line_id=line["line_id"],
                sku=line["sku"],
                name=line["name"],
                quantity=line["quantity"],
                unit_price_cents=line["unit_price_cents"],
                reservation_id=line["reservation_id"],
            )
            for line in conn.execute(
                "SELECT * FROM order_lines WHERE order_id = ? ORDER BY position",
                (row["order_id"],),
            )
        ]
        return Order(
            order_id=row["order_id"],
            customer_id=row["customer_id"],
            status=OrderStatus(row["status"]),
            payment_method=PaymentMethod(row["payment_method"]),
            payment_reference=row["payment_reference"],
            currency=row["currency"],
            lines=lines,
            totals=Totals(
                subtotal_cents=row["subtotal_cents"],
                discount_cents=row["discount_cents"],
                shipping_cents=row["shipping_cents"],
                tax_cents=row["tax_cents"],
                total_cents=row["total_cents"],
            ),
            shipping_address=ShippingAddress.model_validate(json.loads(row["shipping_address"])),
            placed_at=datetime.fromisoformat(row["placed_at"]),
            confirmed_at=_dt(row["confirmed_at"]),
            shipped_at=_dt(row["shipped_at"]),
            carrier=row["carrier"],
            tracking_number=row["tracking_number"],
            cancelled_at=_dt(row["cancelled_at"]),
            cancel_reason=CancelReason(row["cancel_reason"]) if row["cancel_reason"] else None,
            amount_paid_cents=conn.execute(
                "SELECT COALESCE(SUM(amount_cents), 0) FROM payments WHERE order_id = ?",
                (row["order_id"],),
            ).fetchone()[0],
        )
