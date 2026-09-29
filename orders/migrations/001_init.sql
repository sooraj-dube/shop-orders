CREATE TABLE orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    status TEXT NOT NULL,
    payment_method TEXT NOT NULL,
    payment_reference TEXT NOT NULL,
    currency TEXT NOT NULL,
    subtotal_cents INTEGER NOT NULL,
    discount_cents INTEGER NOT NULL,
    shipping_cents INTEGER NOT NULL,
    tax_cents INTEGER NOT NULL,
    total_cents INTEGER NOT NULL,
    shipping_address TEXT NOT NULL,
    placed_at TEXT NOT NULL,
    confirmed_at TEXT,
    shipped_at TEXT,
    carrier TEXT,
    tracking_number TEXT,
    cancelled_at TEXT,
    cancel_reason TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX orders_customer ON orders (customer_id, placed_at);
CREATE UNIQUE INDEX orders_payment_reference ON orders (payment_reference);

CREATE TABLE order_lines (
    line_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders (order_id),
    position INTEGER NOT NULL,
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
    reservation_id TEXT NOT NULL
);

CREATE INDEX order_lines_order ON order_lines (order_id, position);

CREATE TABLE idempotency_keys (
    key TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders (order_id),
    created_at TEXT NOT NULL
);
