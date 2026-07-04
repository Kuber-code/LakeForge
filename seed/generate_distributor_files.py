"""Generate synthetic distributor drop files for the landing volume (FR-4.1).

Produces one day's drop:
- ``shipments_<date>_<batch>.csv``  — distributor shipment confirmations;
- ``returns_<date>_<batch>.json``   — product returns (JSON lines).

Files land in a local output directory; upload them to the landing volume
with the Databricks CLI, e.g.:

    python seed/generate_distributor_files.py --date 2026-07-04 --out out/
    databricks fs cp out/shipments_2026-07-04_1.csv \
        dbfs:/Volumes/lakeforge_dev/bronze/landing/shipments/
    databricks fs cp out/returns_2026-07-04_1.json \
        dbfs:/Volumes/lakeforge_dev/bronze/landing/returns/

Deterministic per (date, batch): re-generating and re-uploading the same file
is harmless — Auto Loader ingests each file exactly once (FR-4.6).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

DISTRIBUTORS = ["BeerLine", "HopTrans", "Chmielex", "GoldenKeg", "BrewLog"]
WAREHOUSES = ["WAW-1", "POZ-1", "GDA-2", "KRK-1"]
SKUS = [f"SKU-{i:03d}" for i in range(1, 41)]
RETURN_REASONS = ["damaged", "expired", "wrong_item", "quality_complaint"]


def generate_shipments(day: date, batch: int, n: int) -> list[dict]:
    rng = random.Random(f"shipments-{day}-{batch}")
    base_id = int(day.strftime("%Y%m%d")) * 1000 + batch * 200
    return [
        {
            "shipment_id": base_id + i,
            "order_id": rng.randint(1, 500),
            "distributor": rng.choice(DISTRIBUTORS),
            "ship_date": (day - timedelta(days=rng.randint(0, 2))).isoformat(),
            "qty_cases": rng.randint(1, 120),
            "warehouse": rng.choice(WAREHOUSES),
        }
        for i in range(n)
    ]


def generate_returns(day: date, batch: int, n: int) -> list[dict]:
    rng = random.Random(f"returns-{day}-{batch}")
    base_id = int(day.strftime("%Y%m%d")) * 1000 + batch * 200
    return [
        {
            "return_id": base_id + i,
            "order_id": rng.randint(1, 500),
            "product_sku": rng.choice(SKUS),
            "return_date": day.isoformat(),
            "quantity": rng.randint(1, 24),
            "reason": rng.choice(RETURN_REASONS),
        }
        for i in range(n)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--batch", type=int, default=1, help="batch number within the day")
    parser.add_argument("--shipments", type=int, default=60)
    parser.add_argument("--returns", type=int, default=15)
    parser.add_argument("--out", type=Path, default=Path("out"))
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    stem = f"{args.date.isoformat()}_{args.batch}"

    shipments = generate_shipments(args.date, args.batch, args.shipments)
    csv_path = args.out / f"shipments_{stem}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(shipments[0].keys()))
        writer.writeheader()
        writer.writerows(shipments)

    returns = generate_returns(args.date, args.batch, args.returns)
    json_path = args.out / f"returns_{stem}.json"
    with json_path.open("w", encoding="utf-8") as fh:
        for row in returns:
            fh.write(json.dumps(row) + "\n")

    print(f"wrote {csv_path} ({len(shipments)} rows)")
    print(f"wrote {json_path} ({len(returns)} rows)")


if __name__ == "__main__":
    main()
