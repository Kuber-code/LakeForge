"""FR-4.3 — silver layer: dedup, typing, referential checks, SCD2, CDF.

Conformance rules:
- every entity is deduplicated to the latest version per business key;
- ``silver.customers`` is a full SCD Type 2 history (``valid_from`` /
  ``valid_to`` / ``is_current``) maintained by MERGE;
- transactional entities (orders, order_lines, deliveries, products,
  shipments, returns) are upserted by MERGE on their business key;
- ``silver.orders`` has Change Data Feed enabled (the CDF demo table);
- referential violations are counted, flagged, and reported — not dropped.

Every MERGE is idempotent: re-running silver over the same bronze state
changes nothing (FR-4.6).
"""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from lakeforge.config import LakeforgeConfig

# Columns whose change triggers a new SCD2 version of a customer.
CUSTOMER_TRACKED_COLS = ["customer_name", "city", "region", "segment", "credit_limit"]

# Business keys of the silver upsert tables (bronze table -> pk).
UPSERT_KEYS = {
    "products": "product_id",
    "orders": "order_id",
    "order_lines": "order_line_id",
    "deliveries": "delivery_id",
    "shipments": "shipment_id",
    "returns": "return_id",
}

# Casts applied to the file-based sources (Auto Loader CSV reads as strings).
FILE_CASTS: dict[str, dict[str, str]] = {
    "shipments": {
        "shipment_id": "int",
        "order_id": "int",
        "distributor": "string",
        "ship_date": "date",
        "qty_cases": "int",
        "warehouse": "string",
    },
    "returns": {
        "return_id": "int",
        "order_id": "int",
        "product_sku": "string",
        "return_date": "date",
        "quantity": "int",
        "reason": "string",
    },
}

_SCD2_COLS = ("valid_from", "valid_to", "is_current")


def latest_per_key(df: DataFrame, pk: str, order_col: str = "modified_at") -> DataFrame:
    """Collapse a bronze increment to the newest version per business key."""
    tiebreak = [F.col(order_col).desc()]
    if "_ingest_ts" in df.columns:
        tiebreak.append(F.col("_ingest_ts").desc())
    w = Window.partitionBy(pk).orderBy(*tiebreak)
    return df.withColumn("_rn", F.row_number().over(w)).where("_rn = 1").drop("_rn")


def apply_casts(df: DataFrame, casts: dict[str, str]) -> DataFrame:
    """Project and cast the declared columns, keeping load metadata."""
    meta = [c for c in df.columns if c.startswith("_") and c != "_rescued_data"]
    typed = [F.col(c).cast(t).alias(c) for c, t in casts.items()]
    return df.select(*typed, *[F.col(c) for c in meta])


def referential_violations(child: DataFrame, parent: DataFrame, key: str) -> DataFrame:
    """Rows of ``child`` whose ``key`` does not exist in ``parent``."""
    return child.join(parent.select(key).distinct(), on=key, how="left_anti")


def _drop_bronze_meta(df: DataFrame) -> DataFrame:
    return df.drop("_source_system", "_source_table", "_rescued_data")


def scd2_upsert(
    spark: SparkSession,
    target: str,
    updates: DataFrame,
    pk: str,
    tracked: list[str],
    effective_col: str = "modified_at",
) -> None:
    """Maintain an SCD Type 2 table via MERGE INTO (FR-4.3).

    ``updates`` must hold at most one row per key (use ``latest_per_key``
    first); versions superseded within the same batch collapse to the latest,
    which is the standard daily-batch semantics.

    The MERGE closes the current version of every key whose tracked columns
    changed (NULL-safe comparison); a second pass appends the new current
    versions. Unchanged rows fail the change predicate, so re-runs are no-ops.
    """
    if not spark.catalog.tableExists(target):
        initial = updates.withColumns(
            {
                "valid_from": F.col(effective_col).cast("timestamp"),
                "valid_to": F.lit(None).cast("timestamp"),
                "is_current": F.lit(True),
            }
        )
        initial.write.saveAsTable(target)
        return

    change_sql = " OR ".join(f"NOT (s.{c} <=> t.{c})" for c in tracked)
    updates.createOrReplaceTempView("_scd2_updates")
    spark.sql(
        f"""
        MERGE INTO {target} t
        USING _scd2_updates s
        ON t.{pk} = s.{pk} AND t.is_current = true
        WHEN MATCHED AND ({change_sql}) THEN UPDATE SET
            t.is_current = false,
            t.valid_to = CAST(s.{effective_col} AS TIMESTAMP)
        """
    )

    # Insert the new current version for keys that are new or just closed.
    current = spark.table(target).where("is_current = true").select(pk)
    new_versions = updates.join(current, on=pk, how="left_anti").withColumns(
        {
            "valid_from": F.col(effective_col).cast("timestamp"),
            "valid_to": F.lit(None).cast("timestamp"),
            "is_current": F.lit(True),
        }
    )
    new_versions.write.mode("append").saveAsTable(target)


def upsert(spark: SparkSession, target: str, updates: DataFrame, pk: str) -> None:
    """MERGE-by-key upsert used by every non-SCD2 silver table."""
    if not spark.catalog.tableExists(target):
        updates.write.saveAsTable(target)
        return

    updates.createOrReplaceTempView("_upsert_updates")
    spark.sql(
        f"""
        MERGE INTO {target} t
        USING _upsert_updates s
        ON t.{pk} = s.{pk}
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
        """
    )


def run_silver(spark: SparkSession, cfg: LakeforgeConfig) -> dict[str, str]:
    """Bronze -> silver for all entities; returns metrics for ops logging."""
    metrics: dict[str, str] = {}

    # SCD2 customers.
    customers = latest_per_key(
        _drop_bronze_meta(spark.table(cfg.table("bronze", "customers"))), "customer_id"
    )
    scd2_upsert(
        spark,
        cfg.table("silver", "customers"),
        customers,
        pk="customer_id",
        tracked=CUSTOMER_TRACKED_COLS,
    )
    metrics["customers_in"] = str(customers.count())

    # Upserted SQL entities. silver.orders is created with CDF enabled.
    orders_target = cfg.table("silver", "orders")
    if not spark.catalog.tableExists(orders_target):
        spark.sql(
            f"""
            CREATE TABLE {orders_target} (
                order_id INT, customer_id INT, order_date DATE,
                status STRING, channel STRING,
                created_at TIMESTAMP, modified_at TIMESTAMP, _ingest_ts TIMESTAMP
            ) TBLPROPERTIES (delta.enableChangeDataFeed = true)
            """
        )

    for table in ("products", "orders", "order_lines", "deliveries"):
        src = _drop_bronze_meta(spark.table(cfg.table("bronze", table)))
        updates = latest_per_key(src, UPSERT_KEYS[table])
        if table == "orders":
            # Align to the CDF-enabled table's declared column order.
            updates = updates.select(
                "order_id",
                "customer_id",
                "order_date",
                "status",
                "channel",
                "created_at",
                "modified_at",
                "_ingest_ts",
            )
        upsert(spark, cfg.table("silver", table), updates, UPSERT_KEYS[table])
        metrics[f"{table}_in"] = str(updates.count())

    # File-based entities: cast from Auto Loader strings, then upsert.
    for table, casts in FILE_CASTS.items():
        bronze = cfg.table("bronze", table)
        if not spark.catalog.tableExists(bronze):
            continue
        updates = latest_per_key(
            apply_casts(spark.table(bronze), casts), UPSERT_KEYS[table], "_ingest_ts"
        )
        upsert(spark, cfg.table("silver", table), updates, UPSERT_KEYS[table])
        metrics[f"{table}_in"] = str(updates.count())

    # Referential check: orders must point at a known customer (any version).
    violations = referential_violations(
        spark.table(cfg.table("silver", "orders")),
        spark.table(cfg.table("silver", "customers")),
        "customer_id",
    )
    metrics["orders_ref_violations"] = str(violations.count())

    return metrics
