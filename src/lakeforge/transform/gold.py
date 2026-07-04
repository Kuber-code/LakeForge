"""FR-4.4 — gold layer: star schema plus dashboard aggregates.

Tables:
- ``dim_customer``  — SCD2 projection of silver.customers with surrogate keys;
- ``dim_product``   — SCD1 projection of silver.products;
- ``dim_date``      — calendar spanning the observed order dates;
- ``fact_sales``    — one row per order line, point-in-time joined to the
  customer version valid on the order date;
- ``agg_daily_revenue`` — net revenue and volume by day / brand / region;
- ``agg_delivery_sla``  — delivery on-time rate by day / carrier.

Gold is rebuilt with a deterministic overwrite on every run: same silver in,
same gold out, so re-runs cannot duplicate anything (FR-4.6).
"""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from lakeforge.config import LakeforgeConfig


def build_dim_customer(customers_scd2: DataFrame) -> DataFrame:
    """Surrogate-keyed SCD2 customer dimension (key is stable per version)."""
    return customers_scd2.select(
        F.xxhash64("customer_id", "valid_from").alias("customer_sk"),
        "customer_id",
        "customer_name",
        "city",
        "region",
        "segment",
        "credit_limit",
        "valid_from",
        "valid_to",
        "is_current",
    )


def build_dim_product(products: DataFrame) -> DataFrame:
    return products.select(
        F.xxhash64("product_id").alias("product_sk"),
        "product_id",
        "sku",
        "product_name",
        "brand",
        "category",
        "unit_price",
        "package",
    )


def build_dim_date(orders: DataFrame) -> DataFrame:
    """Calendar covering the full span of observed order dates."""
    bounds = orders.agg(F.min("order_date").alias("lo"), F.max("order_date").alias("hi")).collect()[
        0
    ]
    return (
        orders.sparkSession.range(1)
        .select(F.explode(F.sequence(F.lit(bounds["lo"]), F.lit(bounds["hi"]))).alias("date"))
        .select(
            F.date_format("date", "yyyyMMdd").cast("int").alias("date_key"),
            F.col("date"),
            F.year("date").alias("year"),
            F.quarter("date").alias("quarter"),
            F.month("date").alias("month"),
            F.dayofweek("date").alias("day_of_week"),
            (F.dayofweek("date").isin(1, 7)).alias("is_weekend"),
        )
    )


def build_fact_sales(
    order_lines: DataFrame, orders: DataFrame, dim_customer: DataFrame, dim_product: DataFrame
) -> DataFrame:
    """One row per order line with point-in-time customer surrogate key.

    The customer version valid on the order date wins; orders predating the
    earliest known version fall back to that earliest version so the fact
    never leaks null surrogate keys.
    """
    o = orders.select("order_id", "customer_id", "order_date", "status", "channel")
    lines = order_lines.select(
        "order_line_id", "order_id", "product_id", "quantity", "unit_price", "discount_pct"
    ).join(o, "order_id")

    order_ts = F.col("order_date").cast("timestamp")
    pit = (
        lines.alias("l")
        .join(
            dim_customer.alias("c"),
            (F.col("l.customer_id") == F.col("c.customer_id"))
            & (F.col("c.valid_from") <= order_ts)
            & (F.col("c.valid_to").isNull() | (order_ts < F.col("c.valid_to"))),
            "left",
        )
        .select("l.*", F.col("c.customer_sk").alias("customer_sk_pit"))
    )

    earliest = (
        dim_customer.withColumn(
            "_rn",
            F.row_number().over(Window.partitionBy("customer_id").orderBy("valid_from")),
        )
        .where("_rn = 1")
        .select("customer_id", F.col("customer_sk").alias("customer_sk_first"))
    )

    return (
        pit.join(earliest, "customer_id", "left")
        .join(dim_product.select("product_sk", "product_id"), "product_id", "left")
        .select(
            "order_line_id",
            "order_id",
            F.coalesce("customer_sk_pit", "customer_sk_first").alias("customer_sk"),
            "product_sk",
            F.date_format("order_date", "yyyyMMdd").cast("int").alias("date_key"),
            "order_date",
            "status",
            "channel",
            "quantity",
            "unit_price",
            "discount_pct",
            (
                F.col("quantity")
                * F.col("unit_price")
                * (F.lit(1) - F.col("discount_pct") / F.lit(100))
            )
            .cast("decimal(14,2)")
            .alias("net_amount"),
        )
    )


def build_agg_daily_revenue(
    fact_sales: DataFrame, dim_customer: DataFrame, dim_product: DataFrame
) -> DataFrame:
    """FR-8.1 feed: net revenue and volume by day, brand and customer region."""
    return (
        fact_sales.where("status <> 'cancelled'")
        .join(dim_product.select("product_sk", "brand"), "product_sk")
        .join(dim_customer.select("customer_sk", "region"), "customer_sk")
        .groupBy("order_date", "brand", "region")
        .agg(
            F.sum("net_amount").alias("net_revenue"),
            F.sum("quantity").alias("units_sold"),
            F.countDistinct("order_id").alias("orders"),
        )
    )


def build_agg_delivery_sla(deliveries: DataFrame) -> DataFrame:
    """FR-8.1 feed: on-time delivery rate by planned day and carrier."""
    delivered = deliveries.where(F.col("actual_date").isNotNull())
    return (
        delivered.groupBy("planned_date", "carrier")
        .agg(
            F.count("*").alias("deliveries"),
            F.sum((F.col("actual_date") <= F.col("planned_date")).cast("int")).alias("on_time"),
            F.avg(F.datediff("actual_date", "planned_date")).alias("avg_delay_days"),
        )
        .withColumn("on_time_rate", F.col("on_time") / F.col("deliveries"))
    )


def build_agg_distributor_shipments(shipments: DataFrame) -> DataFrame:
    """FR-8.1 feed from the file-based source: distributor volume by day.

    This is the gold table fed by the distributor drops (FR-4.1), so the star
    schema side of gold comes from Azure SQL and this one from files — the P2
    exit criterion's "both sources".
    """
    return shipments.groupBy("ship_date", "distributor").agg(
        F.count("*").alias("shipments"),
        F.sum("qty_cases").alias("cases_shipped"),
        F.countDistinct("warehouse").alias("warehouses_used"),
    )


def run_gold(spark: SparkSession, cfg: LakeforgeConfig) -> dict[str, str]:
    """Silver -> gold full rebuild; returns metrics for ops logging."""
    silver = lambda name: spark.table(cfg.table("silver", name))  # noqa: E731

    dim_customer = build_dim_customer(silver("customers"))
    dim_product = build_dim_product(silver("products"))
    dim_date = build_dim_date(silver("orders"))
    fact_sales = build_fact_sales(
        silver("order_lines"), silver("orders"), dim_customer, dim_product
    )
    agg_revenue = build_agg_daily_revenue(fact_sales, dim_customer, dim_product)
    agg_sla = build_agg_delivery_sla(silver("deliveries"))

    outputs = {
        "dim_customer": dim_customer,
        "dim_product": dim_product,
        "dim_date": dim_date,
        "fact_sales": fact_sales,
        "agg_daily_revenue": agg_revenue,
        "agg_delivery_sla": agg_sla,
    }
    if spark.catalog.tableExists(cfg.table("silver", "shipments")):
        outputs["agg_distributor_shipments"] = build_agg_distributor_shipments(silver("shipments"))
    metrics: dict[str, str] = {}
    for name, df in outputs.items():
        target = cfg.table("gold", name)
        df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(target)
        metrics[name] = str(spark.table(target).count())
    return metrics
