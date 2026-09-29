ALTER TABLE orders ADD COLUMN expired_at TEXT;
ALTER TABLE orders ADD COLUMN stock_released_at TEXT;

CREATE INDEX orders_status_placed ON orders (status, placed_at);
