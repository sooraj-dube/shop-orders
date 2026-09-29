# shop-orders

Order lifecycle: placing orders, confirming bank-transfer orders when the money arrives,
cancellation, and shipping status.

Card orders start as `confirmed`. Bank-transfer orders start as `awaiting_payment` and are
confirmed when transfers for the full total have arrived. A bank-transfer order that is not
paid within `PAYMENT_WINDOW_HOURS` becomes `expired` and the stock held for its lines is
released. The worker checks for such orders every `ORDER_EXPIRY_INTERVAL_SECONDS`.

## HTTP API

| Method | Path | Notes |
|---|---|---|
| POST | `/orders` | Requires `Idempotency-Key`. 201 on create, 200 when the key was already used |
| GET | `/orders/{order_id}` | |
| GET | `/customers/{customer_id}/orders?limit=20` | Newest first |
| POST | `/orders/{order_id}/cancel` | `{"reason": "customer_request" \| "fraud_review" \| "merchant_request"}` |
| POST | `/payments/bank-transfers` | Bank notification. Outcome: `confirmed`, `partially_paid`, `needs_refund`, `duplicate` |
| GET | `/healthz` | |

## Events

| Direction | Stream | Event type |
|---|---|---|
| Publishes | `orders.events` | `order.confirmed`, `order.cancelled` |
| Consumes | `warehouse.events` | `shipment.dispatched` (consumer group `orders`) |

## Configuration

| Variable | Default |
|---|---|
| `ORDERS_DATABASE_PATH` | `orders.db` |
| `REDIS_URL` | `redis://localhost:6379/0` |
| `INVENTORY_URL` | `http://localhost:8001` |
| `PAYMENT_WINDOW_HOURS` | `72` |
| `ORDER_EXPIRY_INTERVAL_SECONDS` | `300` |
| `CONSUMER_NAME` | host name |
| `LOG_LEVEL` | `INFO` |

## Run

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ../shop-platform -e ".[dev]"
uvicorn orders.app:create_app --factory --port 8002
python -m orders.worker
```

## Test

```bash
ruff check . && ruff format --check .
pytest
```
