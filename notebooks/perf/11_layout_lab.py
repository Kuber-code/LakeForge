# Databricks notebook source
# MAGIC %md
# MAGIC # Perf lab — layout experiments (FR-7.3)
# MAGIC
# MAGIC Same three queries against five physical layouts of the identical data:
# MAGIC many-small-files baseline, OPTIMIZE-compacted, Z-ORDER, liquid clustering,
# MAGIC and the over-partitioning anti-pattern. Median warm duration per query
# MAGIC lands in `ops.benchmarks` (category `layout`).

# COMMAND ----------

import os
import sys
from datetime import UTC, datetime

sys.path.append(os.path.abspath("../../src"))

from lakeforge.config import for_env
from lakeforge.ops import log_run
from lakeforge.perf.bench import bench_query, ensure_benchmarks_table
from lakeforge.perf.generator import HOT_CUSTOMER_ID, PERF_SCHEMA

dbutils.widgets.text("env", "dev")
dbutils.widgets.text("storage_account", "stlakeforgedevsh93zt")

cfg = for_env(dbutils.widgets.get("env"), dbutils.widgets.get("storage_account"))
ensure_benchmarks_table(spark, cfg)

VARIANTS = ("smallfiles", "compacted", "zorder", "liquid", "overpartitioned")

# A cold key (not the hot one) so selectivity is real; a 30-day date window.
COLD_CUSTOMER = 4711
QUERIES = {
    # data skipping on both clustering keys — where Z-ORDER/liquid should win
    "selective_customer_window": f"""
        SELECT sale_date, sum(revenue) AS revenue
        FROM {{table}}
        WHERE customer_id = {COLD_CUSTOMER}
          AND sale_date BETWEEN '2024-03-01' AND '2024-03-30'
        GROUP BY sale_date
    """,
    # single-day scan — the only query where per-day partitioning shines
    "single_day": """
        SELECT channel, count(*) AS sales, sum(revenue) AS revenue
        FROM {table}
        WHERE sale_date = '2024-06-15'
        GROUP BY channel
    """,
    # full-table aggregation — small files and partition overhead hurt here
    "full_scan_agg": """
        SELECT region, count(*) AS sales, sum(revenue) AS revenue
        FROM {table}
        GROUP BY region
    """,
}

# COMMAND ----------

started = datetime.now(UTC)
for variant in VARIANTS:
    table = cfg.table(PERF_SCHEMA, f"fact_{variant}")
    for query_name, sql_template in QUERIES.items():
        ms = bench_query(
            spark,
            cfg,
            category="layout",
            name=f"{query_name}__{variant}",
            sql=sql_template.format(table=table),
            config={"variant": variant, "query": query_name, "table": table},
        )
        print(f"{variant:16s} {query_name:28s} {ms} ms")

# hot-key selectivity for contrast (skew visible even with clustering)
for variant in ("compacted", "liquid"):
    table = cfg.table(PERF_SCHEMA, f"fact_{variant}")
    bench_query(
        spark,
        cfg,
        category="layout",
        name=f"selective_hot_customer__{variant}",
        sql=f"SELECT count(*), sum(revenue) FROM {table} WHERE customer_id = {HOT_CUSTOMER_ID}",
        config={"variant": variant, "query": "selective_hot_customer", "table": table},
    )

log_run(spark, cfg, task="perf_layout_lab", status="succeeded", started_at=started)
print("layout lab complete")
