from pyspark.sql import functions as F

from lakeforge.perf.bench import (
    bench_query,
    ensure_benchmarks_table,
    explain_text,
    record,
    table_stats,
)
from lakeforge.perf.generator import (
    HOT_CUSTOMER_ID,
    N_CUSTOMERS,
    N_PRODUCTS,
    PERF_SCHEMA,
    synthetic_customers,
    synthetic_products,
    synthetic_sales,
    write_layout_variants,
)

ROWS = 20_000


def test_synthetic_sales_is_deterministic(spark):
    a = synthetic_sales(spark, ROWS)
    b = synthetic_sales(spark, ROWS)
    assert a.count() == ROWS
    assert a.exceptAll(b).count() == 0


def test_synthetic_sales_shape(spark):
    df = synthetic_sales(spark, ROWS)

    # ~30% of rows hit the hot key (skew-join material for FR-7.4)
    hot_share = df.where(F.col("customer_id") == HOT_CUSTOMER_ID).count() / ROWS
    assert 0.25 < hot_share < 0.35

    bounds = df.agg(
        F.min("sale_date").alias("lo"),
        F.max("sale_date").alias("hi"),
        F.max("customer_id").alias("max_cust"),
        F.max("product_id").alias("max_prod"),
        F.countDistinct("order_ref").alias("refs"),
    ).collect()[0]
    assert str(bounds["lo"]) >= "2023-01-01"
    assert str(bounds["hi"]) <= "2025-12-31"
    assert bounds["max_cust"] < N_CUSTOMERS
    assert bounds["max_prod"] < N_PRODUCTS
    # order_ref is the high-cardinality Z-ORDER column: unique per row
    assert bounds["refs"] == ROWS

    # revenue is consistent with quantity * unit_price
    mismatches = df.where(
        F.col("revenue") != (F.col("quantity") * F.col("unit_price")).cast("decimal(12,2)")
    ).count()
    assert mismatches == 0


def test_dimensions_cover_fact_keys(spark):
    fact = synthetic_sales(spark, ROWS)
    customers = synthetic_customers(spark)
    products = synthetic_products(spark)
    assert customers.count() == N_CUSTOMERS
    assert products.count() == N_PRODUCTS

    orphans = (
        fact.join(customers, "customer_id", "left_anti").count()
        + fact.join(products, "product_id", "left_anti").count()
    )
    assert orphans == 0


def test_write_layout_variants_builds_identical_tables(spark, cfg):
    variants = write_layout_variants(spark, cfg, rows=5_000, small_file_partitions=8)
    assert set(variants) == {"smallfiles", "compacted", "zorder", "liquid", "overpartitioned"}

    source_count = spark.table(cfg.table(PERF_SCHEMA, "fact_source")).count()
    assert source_count == 5_000
    for table in variants.values():
        assert spark.table(table).count() == source_count

    small = table_stats(spark, variants["smallfiles"])
    compacted = table_stats(spark, variants["compacted"])
    assert int(small["num_files"]) > int(compacted["num_files"])

    assert table_stats(spark, variants["overpartitioned"])["partition_columns"] == "sale_date"
    assert "customer_id" in table_stats(spark, variants["liquid"])["clustering_columns"]


def test_bench_query_records_median_and_metrics(spark, cfg):
    ensure_benchmarks_table(spark, cfg)
    spark.range(100).write.mode("overwrite").saveAsTable(cfg.table("ops", "bench_probe"))

    ms = bench_query(
        spark,
        cfg,
        category="layout",
        name="unit_probe",
        sql=f"SELECT * FROM {cfg.table('ops', 'bench_probe')} WHERE id < 50",
        config={"variant": "unit"},
        runs=3,
    )
    assert ms >= 0

    row = (
        spark.table(cfg.table("ops", "benchmarks"))
        .where(F.col("name") == "unit_probe")
        .collect()[0]
    )
    assert row["category"] == "layout"
    assert row["config"]["variant"] == "unit"
    assert row["metrics"]["rows_out"] == "50"
    assert len(row["metrics"]["all_runs_ms"].split(",")) == 3


def test_record_and_explain(spark, cfg):
    ensure_benchmarks_table(spark, cfg)
    bench_id = record(
        spark,
        cfg,
        category="maintenance",
        name="unit_record",
        duration_ms=12,
        metrics={"files": 3},
    )
    stored = (
        spark.table(cfg.table("ops", "benchmarks")).where(F.col("bench_id") == bench_id).collect()
    )
    assert len(stored) == 1
    assert stored[0]["metrics"]["files"] == "3"

    plan = explain_text(spark, "SELECT 1 AS one")
    assert "Physical Plan" in plan
