CREATE TABLE payments (
    payment_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders (order_id),
    bank_transaction_id TEXT NOT NULL UNIQUE,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    currency TEXT NOT NULL,
    received_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX payments_order ON payments (order_id);
