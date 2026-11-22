"""Create and seed the sample analytics database.

Usage:  python scripts/seed_db.py [sqlite:///data/sample.db]

The schema always contains an `orders` table with `id` and `order_date`
columns (used by Verification Test Case 1) plus supporting tables so charts
have something interesting to show.
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parent.parent

SCHEMA = """
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
    id      INTEGER PRIMARY KEY,
    name    VARCHAR(80) NOT NULL,
    country VARCHAR(40) NOT NULL
);

CREATE TABLE products (
    id       INTEGER PRIMARY KEY,
    name     VARCHAR(80) NOT NULL,
    category VARCHAR(40) NOT NULL,
    price    NUMERIC(10, 2) NOT NULL
);

CREATE TABLE orders (
    id          INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    product_id  INTEGER NOT NULL REFERENCES products(id),
    order_date  DATE NOT NULL,
    quantity    INTEGER NOT NULL,
    amount      NUMERIC(10, 2) NOT NULL,
    region      VARCHAR(20) NOT NULL,
    status      VARCHAR(20) NOT NULL
);
"""

CUSTOMERS = [
    ("Acme Corp", "USA"), ("Globex", "Germany"), ("Initech", "USA"),
    ("Umbrella Ltd", "UK"), ("Stark Industries", "USA"), ("Wayne Enterprises", "Canada"),
    ("Hooli", "USA"), ("Soylent", "India"), ("Wonka Co", "UK"), ("Tyrell Corp", "Japan"),
]
PRODUCTS = [
    ("Laptop", "Electronics", 1200.00), ("Phone", "Electronics", 800.00),
    ("Desk", "Furniture", 350.00), ("Chair", "Furniture", 150.00),
    ("Notebook", "Stationery", 5.50), ("Pen Set", "Stationery", 12.00),
    ("Monitor", "Electronics", 300.00), ("Bookshelf", "Furniture", 210.00),
]
REGIONS = ["North", "South", "East", "West"]
STATUSES = ["completed", "completed", "completed", "pending", "cancelled"]


def seed(database_url: str, n_orders: int = 300, rng_seed: int = 42) -> None:
    engine = create_engine(database_url, future=True)
    rng = random.Random(rng_seed)
    with engine.begin() as conn:
        for stmt in filter(None, (s.strip() for s in SCHEMA.split(";"))):
            conn.execute(text(stmt))
        for i, (name, country) in enumerate(CUSTOMERS, 1):
            conn.execute(
                text("INSERT INTO customers VALUES (:i, :n, :c)"), {"i": i, "n": name, "c": country}
            )
        for i, (name, cat, price) in enumerate(PRODUCTS, 1):
            conn.execute(
                text("INSERT INTO products VALUES (:i, :n, :c, :p)"),
                {"i": i, "n": name, "c": cat, "p": price},
            )
        start = date(2025, 1, 1)
        for i in range(1, n_orders + 1):
            pid = rng.randint(1, len(PRODUCTS))
            qty = rng.randint(1, 5)
            price = PRODUCTS[pid - 1][2]
            conn.execute(
                text("INSERT INTO orders VALUES (:i, :c, :p, :d, :q, :a, :r, :s)"),
                {
                    "i": i,
                    "c": rng.randint(1, len(CUSTOMERS)),
                    "p": pid,
                    "d": (start + timedelta(days=rng.randint(0, 364))).isoformat(),
                    "q": qty,
                    "a": round(price * qty, 2),
                    "r": rng.choice(REGIONS),
                    "s": rng.choice(STATUSES),
                },
            )


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else f"sqlite:///{(ROOT / 'data' / 'sample.db').as_posix()}"
    if url.startswith("sqlite:///"):
        Path(url.replace("sqlite:///", "", 1)).parent.mkdir(parents=True, exist_ok=True)
    seed(url)
    print(f"Seeded {url}")
