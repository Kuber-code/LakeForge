"""Seed the brewery OLTP database with synthetic data (FR-1.6).

Idempotent (NFR-5): DDL uses IF OBJECT_ID guards, data is inserted only into
empty tables. Credentials are never passed on the command line or stored in
the repo — they are read from Key Vault via the Azure CLI (you need the
Key Vault Administrator / Secrets User role and network access to the vault).

Usage:
    python seed_sql.py --key-vault <kv-name> --server <fqdn> --database sqldb-brewery-oltp

Requires: pyodbc, ODBC Driver 18 for SQL Server, Azure CLI (logged in).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import subprocess
import sys
from datetime import date, timedelta

import pyodbc

RNG_SEED = 42

REGIONS = {
    "Mazowieckie": ["Warszawa", "Radom", "Plock"],
    "Malopolskie": ["Krakow", "Tarnow", "Nowy Sacz"],
    "Slaskie": ["Katowice", "Gliwice", "Czestochowa"],
    "Pomorskie": ["Gdansk", "Gdynia", "Slupsk"],
    "Wielkopolskie": ["Poznan", "Kalisz", "Leszno"],
    "Dolnoslaskie": ["Wroclaw", "Legnica", "Walbrzych"],
}
SEGMENTS = ["HoReCa", "Retail", "Wholesale"]
BRANDS = ["Zywa Piana", "Golden Hop", "Baltic Dark", "Chmielna 7", "Solar Brew"]
CATEGORIES = ["lager", "IPA", "wheat", "stout", "pilsner", "non-alcoholic"]
PACKAGES = [("keg 30l", 320.0), ("keg 50l", 510.0), ("bottle 0.5l case", 58.0), ("can 0.5l case", 54.0)]
CARRIERS = ["BrewLog", "HopExpress", "TransBeer", "Own fleet"]
CHANNELS = ["direct", "distributor", "online"]

N_CUSTOMERS = 500
N_PRODUCTS = 40
N_ORDERS = 5000
ORDER_WINDOW_DAYS = 180


def kv_secret(vault: str, name: str) -> str:
    out = subprocess.run(
        ["az", "keyvault", "secret", "show", "--vault-name", vault, "--name", name, "-o", "json"],
        capture_output=True, text=True, check=True, shell=sys.platform == "win32",
    )
    return json.loads(out.stdout)["value"]


def connect(server: str, database: str, user: str, password: str) -> pyodbc.Connection:
    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={server},1433;DATABASE={database};UID={user};PWD={password};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=60;"
    )
    # First connection can take ~60s while a paused serverless DB resumes.
    return pyodbc.connect(conn_str)


def run_ddl(cur: pyodbc.Cursor) -> None:
    """Execute schema.sql, one IF-guarded statement per batch."""
    ddl = (pathlib.Path(__file__).parent / "schema.sql").read_text()
    batches: list[list[str]] = []
    for line in ddl.splitlines():
        if line.startswith("--") or not line.strip():
            continue
        if line.startswith("IF "):
            batches.append([line])
        elif batches:
            batches[-1].append(line)
    for batch in batches:
        cur.execute("\n".join(batch))
    cur.commit()


def table_empty(cur: pyodbc.Cursor, table: str) -> bool:
    cur.execute(f"SELECT COUNT(*) FROM dbo.{table}")
    return cur.fetchone()[0] == 0


def seed(cur: pyodbc.Cursor) -> None:
    rng = random.Random(RNG_SEED)
    today = date.today()

    if table_empty(cur, "customers"):
        rows = []
        for i in range(N_CUSTOMERS):
            region = rng.choice(list(REGIONS))
            rows.append((
                f"Customer {i + 1:04d} {rng.choice(['Pub', 'Market', 'Distribution', 'Hotel', 'Restaurant'])}",
                rng.choice(REGIONS[region]), region, rng.choice(SEGMENTS),
                round(rng.uniform(5_000, 250_000), 2),
            ))
        cur.fast_executemany = True
        cur.executemany(
            "INSERT INTO dbo.customers (customer_name, city, region, segment, credit_limit) VALUES (?,?,?,?,?)",
            rows,
        )
        print(f"customers: inserted {len(rows)}")

    if table_empty(cur, "products"):
        rows = []
        for i in range(N_PRODUCTS):
            brand = rng.choice(BRANDS)
            category = rng.choice(CATEGORIES)
            package, base_price = rng.choice(PACKAGES)
            rows.append((
                f"SKU-{i + 1:04d}", f"{brand} {category.title()} {package}",
                brand, category, round(base_price * rng.uniform(0.9, 1.25), 2), package,
            ))
        cur.executemany(
            "INSERT INTO dbo.products (sku, product_name, brand, category, unit_price, package) VALUES (?,?,?,?,?,?)",
            rows,
        )
        print(f"products: inserted {len(rows)}")

    if table_empty(cur, "orders"):
        cur.execute("SELECT customer_id FROM dbo.customers")
        customer_ids = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT product_id, unit_price FROM dbo.products")
        products = cur.fetchall()

        order_rows = []
        for _ in range(N_ORDERS):
            d = today - timedelta(days=rng.randint(0, ORDER_WINDOW_DAYS))
            age = (today - d).days
            status = ("delivered" if age > 14 else rng.choice(["placed", "shipped", "delivered"]))
            if rng.random() < 0.03:
                status = "cancelled"
            order_rows.append((rng.choice(customer_ids), d, status, rng.choice(CHANNELS)))
        cur.fast_executemany = True
        cur.executemany(
            "INSERT INTO dbo.orders (customer_id, order_date, status, channel) VALUES (?,?,?,?)",
            order_rows,
        )
        print(f"orders: inserted {len(order_rows)}")

        cur.execute("SELECT order_id, order_date, status FROM dbo.orders")
        orders = cur.fetchall()

        line_rows = []
        delivery_rows = []
        for order_id, order_date_val, status in orders:
            for product_id, unit_price in rng.sample(products, rng.randint(1, 5)):
                discount = rng.choice([0, 0, 0, 2.5, 5, 10])
                line_rows.append((order_id, product_id, rng.randint(1, 40), float(unit_price), discount))
            if status in ("shipped", "delivered"):
                planned = order_date_val + timedelta(days=rng.randint(1, 5))
                late = rng.random() < 0.15
                actual = planned + timedelta(days=rng.randint(1, 4)) if late else planned
                delivery_rows.append((
                    order_id, planned,
                    actual if status == "delivered" else None,
                    rng.choice(CARRIERS),
                    "delivered" if status == "delivered" else "in_transit",
                ))
        cur.executemany(
            "INSERT INTO dbo.order_lines (order_id, product_id, quantity, unit_price, discount_pct) VALUES (?,?,?,?,?)",
            line_rows,
        )
        print(f"order_lines: inserted {len(line_rows)}")
        cur.executemany(
            "INSERT INTO dbo.deliveries (order_id, planned_date, actual_date, carrier, status) VALUES (?,?,?,?,?)",
            delivery_rows,
        )
        print(f"deliveries: inserted {len(delivery_rows)}")

    cur.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-vault", required=True, help="Key Vault name holding sql-admin-* secrets")
    parser.add_argument("--server", required=True, help="SQL server FQDN")
    parser.add_argument("--database", default="sqldb-brewery-oltp")
    args = parser.parse_args()

    user = kv_secret(args.key_vault, "sql-admin-login")
    password = kv_secret(args.key_vault, "sql-admin-password")

    with connect(args.server, args.database, user, password) as conn:
        cur = conn.cursor()
        run_ddl(cur)
        seed(cur)

    print("Seed complete (re-running is a no-op).")


if __name__ == "__main__":
    main()
