-- E-commerce / logistics analytics schema (target of the agent's SQL).
SET search_path TO shop;

CREATE TABLE sellers (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    city        TEXT,
    state       TEXT,
    country     TEXT DEFAULT 'India',
    rating      NUMERIC(3, 2),            -- 0.00 - 5.00
    created_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE products (
    id            SERIAL PRIMARY KEY,
    seller_id     INTEGER NOT NULL REFERENCES sellers (id),
    name          TEXT NOT NULL,
    category      TEXT NOT NULL,           -- Electronics, Apparel, Home, ...
    price         NUMERIC(10, 2) NOT NULL,
    weight_grams  INTEGER,
    created_at    TIMESTAMPTZ NOT NULL
);

CREATE TABLE customers (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT UNIQUE,
    city        TEXT,
    state       TEXT,
    country     TEXT DEFAULT 'India',
    created_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE addresses (
    id           SERIAL PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers (id),
    line1        TEXT,
    city         TEXT,
    state        TEXT,
    country      TEXT DEFAULT 'India',
    pincode      TEXT,
    type         TEXT DEFAULT 'home'       -- home | work
);

CREATE TABLE orders (
    id            SERIAL PRIMARY KEY,
    customer_id   INTEGER NOT NULL REFERENCES customers (id),
    status        TEXT NOT NULL,            -- placed|confirmed|shipped|delivered|cancelled|returned
    total_amount  NUMERIC(12, 2) NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL
);

CREATE TABLE order_items (
    id          SERIAL PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders (id),
    product_id  INTEGER NOT NULL REFERENCES products (id),
    seller_id   INTEGER NOT NULL REFERENCES sellers (id),
    quantity    INTEGER NOT NULL DEFAULT 1,
    unit_price  NUMERIC(10, 2) NOT NULL,
    line_total  NUMERIC(12, 2) NOT NULL
);

CREATE TABLE payments (
    id        SERIAL PRIMARY KEY,
    order_id  INTEGER NOT NULL REFERENCES orders (id),
    method    TEXT NOT NULL,                -- upi|card|netbanking|cod|wallet
    amount    NUMERIC(12, 2) NOT NULL,
    status    TEXT NOT NULL,                -- success|failed|refunded
    paid_at   TIMESTAMPTZ
);

CREATE TABLE refunds (
    id          SERIAL PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders (id),
    amount      NUMERIC(12, 2) NOT NULL,
    reason      TEXT,                        -- damaged|late|wrong_item|changed_mind
    status      TEXT NOT NULL,               -- requested|approved|rejected|completed
    created_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE couriers (
    id    SERIAL PRIMARY KEY,
    name  TEXT NOT NULL,
    mode  TEXT NOT NULL                      -- air | surface
);

CREATE TABLE shipments (
    id            SERIAL PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders (id),
    courier_id    INTEGER NOT NULL REFERENCES couriers (id),
    status        TEXT NOT NULL,             -- created|in_transit|delivered|failed|returned
    sla_days      INTEGER,
    cost          NUMERIC(10, 2),
    shipped_at    TIMESTAMPTZ,
    delivered_at  TIMESTAMPTZ
);

CREATE TABLE tracking_events (
    id           SERIAL PRIMARY KEY,
    shipment_id  INTEGER NOT NULL REFERENCES shipments (id),
    status       TEXT NOT NULL,              -- picked_up|in_transit|out_for_delivery|delivered|failed
    location     TEXT,
    event_time   TIMESTAMPTZ NOT NULL
);

-- Helpful indexes for realistic plans.
CREATE INDEX idx_orders_created ON orders (created_at);
CREATE INDEX idx_orders_status ON orders (status);
CREATE INDEX idx_order_items_order ON order_items (order_id);
CREATE INDEX idx_order_items_seller ON order_items (seller_id);
CREATE INDEX idx_shipments_order ON shipments (order_id);
CREATE INDEX idx_tracking_shipment ON tracking_events (shipment_id);
