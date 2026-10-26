"""Deterministic Faker seed for the `shop` schema.

Everything is seeded (Faker + random) off a fixed value and anchored to a fixed
"now", so the data — and therefore every gold-SQL result in the eval set — is
reproducible on any machine. Run with `make seed` after the DB is up.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import psycopg
from faker import Faker

from nl2sql.config import get_settings

SEED = 42
# Anchor to seed-time "now" so time-window queries (last 30 days, etc.) return
# real data. Faker/random stay seeded, so names/categories/amounts are stable;
# only absolute timestamps float with the seed date.
NOW = datetime.now(UTC)
N_SELLERS = 40
N_CUSTOMERS = 300
N_PRODUCTS = 300
N_ORDERS = 2000

CATEGORIES = ["Electronics", "Apparel", "Home", "Beauty", "Sports", "Books", "Grocery"]
ORDER_STATUSES = ["placed", "confirmed", "shipped", "delivered", "cancelled", "returned"]
PAY_METHODS = ["upi", "card", "netbanking", "cod", "wallet"]
REFUND_REASONS = ["damaged", "late", "wrong_item", "changed_mind"]
STATES = ["Karnataka", "Maharashtra", "Delhi", "Tamil Nadu", "West Bengal", "Gujarat", "Telangana"]
CITIES = ["Bengaluru", "Mumbai", "Delhi", "Chennai", "Kolkata", "Ahmedabad", "Hyderabad"]
COURIERS = [
    ("BlueDart", "air"),
    ("Delhivery", "surface"),
    ("Ekart", "surface"),
    ("DTDC", "surface"),
    ("IndiaPost", "surface"),
    ("Shadowfax", "air"),
]


def _dt(days_ago_max: int) -> datetime:
    return NOW - timedelta(
        days=random.randint(0, days_ago_max),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )


def main() -> None:
    fake = Faker("en_IN")
    Faker.seed(SEED)
    random.seed(SEED)

    s = get_settings()
    with psycopg.connect(s.app_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SET search_path TO shop")
        cur.execute(
            "TRUNCATE sellers, products, customers, addresses, orders, order_items, "
            "payments, refunds, couriers, shipments, tracking_events RESTART IDENTITY CASCADE"
        )

        # couriers
        for name, mode in COURIERS:
            cur.execute("INSERT INTO couriers (name, mode) VALUES (%s, %s)", (name, mode))
        courier_ids = list(range(1, len(COURIERS) + 1))

        # sellers (one planted "Spike Traders" with high refunds later)
        sellers = []
        for i in range(1, N_SELLERS + 1):
            name = "Spike Traders" if i == 1 else fake.company()
            ci = random.randrange(len(CITIES))
            cur.execute(
                "INSERT INTO sellers (name, city, state, country, rating, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    name,
                    CITIES[ci],
                    STATES[ci],
                    "India",
                    round(random.uniform(3.0, 5.0), 2),
                    _dt(900),
                ),
            )
            sellers.append(i)

        # products
        products = []  # (id, seller_id, price)
        for i in range(1, N_PRODUCTS + 1):
            seller_id = random.choice(sellers)
            price = round(random.uniform(99, 49999), 2)
            cur.execute(
                "INSERT INTO products (seller_id, name, category, price, weight_grams, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    seller_id,
                    fake.word().title() + " " + random.choice(["Pro", "Max", "Lite", "X"]),
                    random.choice(CATEGORIES),
                    price,
                    random.randint(50, 8000),
                    _dt(700),
                ),
            )
            products.append((i, seller_id, price))

        # customers + addresses
        for i in range(1, N_CUSTOMERS + 1):
            ci = random.randrange(len(CITIES))
            cur.execute(
                "INSERT INTO customers (name, email, city, state, country, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (fake.name(), f"user{i}@example.com", CITIES[ci], STATES[ci], "India", _dt(800)),
            )
            for _ in range(random.randint(1, 2)):
                cur.execute(
                    "INSERT INTO addresses "
                    "(customer_id, line1, city, state, country, pincode, type)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (
                        i,
                        fake.street_address(),
                        CITIES[ci],
                        STATES[ci],
                        "India",
                        fake.postcode(),
                        random.choice(["home", "work"]),
                    ),
                )

        # orders + items + payments + shipments + tracking + refunds
        for oid in range(1, N_ORDERS + 1):
            customer_id = random.randint(1, N_CUSTOMERS)
            status = random.choices(ORDER_STATUSES, weights=[5, 8, 12, 55, 12, 8], k=1)[0]
            created = _dt(365)
            cur.execute(
                "INSERT INTO orders (customer_id, status, total_amount, created_at) "
                "VALUES (%s,%s,%s,%s)",
                (customer_id, status, 0, created),
            )
            total = 0.0
            for _ in range(random.randint(1, 4)):
                pid, seller_id, price = random.choice(products)
                qty = random.randint(1, 3)
                line = round(price * qty, 2)
                total += line
                cur.execute(
                    "INSERT INTO order_items "
                    "(order_id, product_id, seller_id, quantity, unit_price, line_total) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (oid, pid, seller_id, qty, price, line),
                )
            total = round(total, 2)
            cur.execute("UPDATE orders SET total_amount=%s WHERE id=%s", (total, oid))

            # payment
            if status != "cancelled":
                pay_status = "refunded" if status == "returned" else "success"
                cur.execute(
                    "INSERT INTO payments (order_id, method, amount, status, paid_at) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (
                        oid,
                        random.choice(PAY_METHODS),
                        total,
                        pay_status,
                        created + timedelta(minutes=random.randint(1, 120)),
                    ),
                )
            else:
                if random.random() < 0.3:
                    cur.execute(
                        "INSERT INTO payments (order_id, method, amount, status, paid_at) "
                        "VALUES (%s,%s,%s,%s,%s)",
                        (oid, random.choice(PAY_METHODS), total, "failed", None),
                    )

            # shipment for anything that shipped
            if status in ("shipped", "delivered", "returned"):
                courier_id = random.choice(courier_ids)
                sla = random.choice([2, 3, 4, 5, 7])
                shipped_at = created + timedelta(days=random.randint(0, 2))
                delivered_at = None
                ship_status = "in_transit"
                if status in ("delivered", "returned"):
                    delivered_at = shipped_at + timedelta(days=random.randint(1, 9))
                    ship_status = "returned" if status == "returned" else "delivered"
                cur.execute(
                    "INSERT INTO shipments "
                    "(order_id, courier_id, status, sla_days, cost, shipped_at, delivered_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (
                        oid,
                        courier_id,
                        ship_status,
                        sla,
                        round(random.uniform(30, 300), 2),
                        shipped_at,
                        delivered_at,
                    ),
                )
                shipment_id = cur.fetchone()[0]
                evt = shipped_at
                for ev in [
                    "picked_up",
                    "in_transit",
                    "out_for_delivery",
                    "delivered" if ship_status == "delivered" else "failed",
                ]:
                    cur.execute(
                        "INSERT INTO tracking_events (shipment_id, status, location, event_time) "
                        "VALUES (%s,%s,%s,%s)",
                        (shipment_id, ev, random.choice(CITIES), evt),
                    )
                    evt += timedelta(hours=random.randint(6, 48))

            # refunds: returned orders always; plus a planted spike on seller 1
            spike = any(p[1] == 1 for p in [random.choice(products)]) and random.random() < 0.5
            if status == "returned" or (status == "delivered" and spike):
                cur.execute(
                    "INSERT INTO refunds (order_id, amount, reason, status, created_at) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (
                        oid,
                        round(total * random.uniform(0.5, 1.0), 2),
                        random.choice(REFUND_REASONS),
                        random.choice(["requested", "approved", "completed", "rejected"]),
                        created + timedelta(days=random.randint(2, 20)),
                    ),
                )

        conn.commit()

        cur.execute("SELECT count(*) FROM orders")
        n_orders = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM order_items")
        n_items = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM shipments")
        n_ship = cur.fetchone()[0]
        print(f"seeded: {n_orders} orders, {n_items} order_items, {n_ship} shipments")


if __name__ == "__main__":
    main()
