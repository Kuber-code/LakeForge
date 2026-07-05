"""FR-7.1 — deterministic synthetic sales fact at 50–100M rows.

The generator is pure column arithmetic over ``spark.range`` — no data files,
no UDFs — so the same ``rows`` argument always yields byte-identical content
and it scales linearly with cores.

Shape choices that later experiments rely on:
- ``customer_id`` is skewed: ~30% of all rows hit the single hot key
  ``HOT_CUSTOMER_ID`` (AQE skew-join material, FR-7.4);
- ``sale_date`` spans three years (partitioning / clustering key);
- ``order_ref`` is effectively unique (high-cardinality Z-ORDER column).
"""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from lakeforge.config import LakeforgeConfig

# Schema holding every perf-lab table, separate from the medallion layers.
PERF_SCHEMA = "perf"

HOT_CUSTOMER_ID = 42
N_CUSTOMERS = 50_000
N_PRODUCTS = 200
N_DAYS = 3 * 365
START_DATE = "2023-01-01"

REGIONS = (
    "mazowieckie",
    "malopolskie",
    "slaskie",
    "wielkopolskie",
    "pomorskie",
    "dolnoslaskie",
    "lodzkie",
    "lubelskie",
)
CHANNELS = ("on_trade", "off_trade", "export")


def ensure_perf_schema(spark: SparkSession, cfg: LakeforgeConfig) -> None:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {cfg.catalog}.{PERF_SCHEMA}")


def _pick(col_name: str, values: tuple[str, ...], salt: int):
    """Deterministic pseudo-random pick from ``values`` keyed on sale_id."""
    idx = F.pmod(F.xxhash64(F.col(col_name), F.lit(salt)), F.lit(len(values)))
    return F.element_at(F.array(*[F.lit(v) for v in values]), (idx + 1).cast("int"))


def synthetic_sales(spark: SparkSession, rows: int) -> DataFrame:
    """One row per sale line; deterministic for a given ``rows``."""
    h = lambda salt: F.xxhash64(F.col("sale_id"), F.lit(salt))  # noqa: E731
    quantity = (F.pmod(h(5), F.lit(24)) + 1).cast("int")
    unit_price = (F.pmod(h(6), F.lit(900)) / 100 + 2).cast("decimal(8,2)")
    return (
        spark.range(rows)
        .withColumnRenamed("id", "sale_id")
        .withColumn(
            "sale_date",
            F.date_add(F.lit(START_DATE).cast("date"), F.pmod(h(1), F.lit(N_DAYS)).cast("int")),
        )
        .withColumn(
            "customer_id",
            F.when(F.pmod(h(2), F.lit(10)) < 3, F.lit(HOT_CUSTOMER_ID))
            .otherwise(F.pmod(h(3), F.lit(N_CUSTOMERS)))
            .cast("bigint"),
        )
        .withColumn("product_id", F.pmod(h(4), F.lit(N_PRODUCTS)).cast("bigint"))
        .withColumn("region", _pick("sale_id", REGIONS, 7))
        .withColumn("channel", _pick("sale_id", CHANNELS, 8))
        .withColumn("quantity", quantity)
        .withColumn("unit_price", unit_price)
        .withColumn("revenue", (quantity * unit_price).cast("decimal(12,2)"))
        .withColumn("order_ref", F.sha1(F.concat_ws("-", F.lit("lf"), F.col("sale_id"))))
    )


def synthetic_customers(spark: SparkSession) -> DataFrame:
    """Small dimension matching the fact's customer key space (join labs)."""
    h = lambda salt: F.xxhash64(F.col("customer_id"), F.lit(salt))  # noqa: E731
    return (
        spark.range(N_CUSTOMERS)
        .withColumnRenamed("id", "customer_id")
        .withColumn("customer_name", F.concat(F.lit("Customer "), F.col("customer_id")))
        .withColumn("region", _pick("customer_id", REGIONS, 11))
        .withColumn("segment", _pick("customer_id", ("horeca", "retail", "wholesale"), 12))
        .withColumn("credit_limit", (F.pmod(h(13), F.lit(500)) * 100).cast("int"))
    )


def synthetic_products(spark: SparkSession) -> DataFrame:
    return (
        spark.range(N_PRODUCTS)
        .withColumnRenamed("id", "product_id")
        .withColumn("product_name", F.concat(F.lit("Brew "), F.col("product_id")))
        .withColumn("brand", _pick("product_id", ("Griffin", "Vistula", "Amber", "Baltic"), 14))
        .withColumn("category", _pick("product_id", ("lager", "ipa", "stout", "pilsner"), 15))
    )


def write_layout_variants(
    spark: SparkSession, cfg: LakeforgeConfig, rows: int, small_file_partitions: int = 1600
) -> dict[str, str]:
    """FR-7.3 — materialize the same fact under five physical layouts.

    Returns {variant name -> fully-qualified table}. Idempotent: every table
    is rebuilt from scratch (CREATE OR REPLACE) so re-runs converge.
    """
    ensure_perf_schema(spark, cfg)
    fact = lambda name: cfg.table(PERF_SCHEMA, name)  # noqa: E731
    src = fact("fact_source")

    synthetic_sales(spark, rows).write.mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(src)
    synthetic_customers(spark).write.mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(fact("dim_customer"))
    synthetic_products(spark).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
        fact("dim_product")
    )

    # 1) many small files — the classic small-files problem
    spark.table(src).repartition(small_file_partitions).write.mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(fact("fact_smallfiles"))

    # 2) same data, then bin-packing OPTIMIZE
    spark.sql(
        f"CREATE OR REPLACE TABLE {fact('fact_compacted')} "
        f"AS SELECT * FROM {fact('fact_smallfiles')}"
    )
    spark.sql(f"OPTIMIZE {fact('fact_compacted')}")

    # 3) OPTIMIZE ZORDER on the selective-query keys
    spark.sql(f"CREATE OR REPLACE TABLE {fact('fact_zorder')} AS SELECT * FROM {src}")
    spark.sql(f"OPTIMIZE {fact('fact_zorder')} ZORDER BY (customer_id, sale_date)")

    # 4) liquid clustering on the same keys
    spark.sql(
        f"CREATE OR REPLACE TABLE {fact('fact_liquid')} CLUSTER BY (customer_id, sale_date) "
        f"AS SELECT * FROM {src}"
    )
    spark.sql(f"OPTIMIZE {fact('fact_liquid')}")

    # 5) over-partitioning anti-pattern: one directory per day, ~1095 of them
    spark.sql(
        f"CREATE OR REPLACE TABLE {fact('fact_overpartitioned')} "
        f"PARTITIONED BY (sale_date) AS SELECT * FROM {src}"
    )

    return {
        "smallfiles": fact("fact_smallfiles"),
        "compacted": fact("fact_compacted"),
        "zorder": fact("fact_zorder"),
        "liquid": fact("fact_liquid"),
        "overpartitioned": fact("fact_overpartitioned"),
    }
