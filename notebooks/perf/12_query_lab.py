# Databricks notebook source
# MAGIC %md
# MAGIC # Perf lab — query optimization before/after (FR-7.4)
# MAGIC
# MAGIC Three deliberately bad queries, each measured, EXPLAINed, rewritten and
# MAGIC measured again — plus broadcast-vs-shuffle and AQE-on/off comparisons.
# MAGIC Results in `ops.benchmarks` (category `query`); full plans printed to the
# MAGIC run log for the findings doc.

# COMMAND ----------

import os
import sys
from datetime import UTC, datetime

sys.path.append(os.path.abspath("../../src"))

from lakeforge.config import for_env
from lakeforge.ops import log_run
from lakeforge.perf.bench import bench_query, ensure_benchmarks_table, explain_text
from lakeforge.perf.generator import PERF_SCHEMA, REGIONS

dbutils.widgets.text("env", "dev")
dbutils.widgets.text("storage_account", "stlakeforgedevsh93zt")

cfg = for_env(dbutils.widgets.get("env"), dbutils.widgets.get("storage_account"))
ensure_benchmarks_table(spark, cfg)

FACT = cfg.table(PERF_SCHEMA, "fact_compacted")
FACT_CLUSTERED = cfg.table(PERF_SCHEMA, "fact_liquid")
CUSTOMERS = cfg.table(PERF_SCHEMA, "dim_customer")
PRODUCTS = cfg.table(PERF_SCHEMA, "dim_product")
PROMOTIONS = cfg.table(PERF_SCHEMA, "dim_promotion")

started = datetime.now(UTC)

# COMMAND ----------

# MAGIC %md ## Setup — weekly per-region promotions (~1 250 rows)

# COMMAND ----------

from pyspark.sql import functions as F  # noqa: E402

promos = (
    spark.range(156)  # 3 years of weeks
    .withColumnRenamed("id", "week")
    .crossJoin(spark.createDataFrame([(r,) for r in REGIONS], ["region"]))
    .select(
        F.monotonically_increasing_id().alias("promo_id"),
        "region",
        F.date_add(F.lit("2023-01-02").cast("date"), (F.col("week") * 7).cast("int")).alias(
            "promo_start"
        ),
        F.date_add(F.lit("2023-01-02").cast("date"), (F.col("week") * 7 + 9).cast("int")).alias(
            "promo_end"
        ),
        (F.pmod(F.xxhash64("week", "region"), F.lit(30)) / 100).alias("discount"),
    )
)
promos.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(PROMOTIONS)
print("promotions:", spark.table(PROMOTIONS).count())

# COMMAND ----------

# MAGIC %md ## Bad query 1 — exploding join, deduped afterwards with DISTINCT
# MAGIC Joins one month of sales to *every* promotion in the region (~156 matches
# MAGIC per row), then filters dates and DISTINCTs the blow-up away. The rewrite
# MAGIC pushes the date-overlap predicate into the join condition.

# COMMAND ----------

BAD_EXPLODING = f"""
    SELECT DISTINCT f.sale_id, f.revenue, p.promo_id
    FROM {FACT} f
    JOIN {PROMOTIONS} p ON f.region = p.region
    WHERE f.sale_date BETWEEN '2024-03-01' AND '2024-03-31'
      AND f.sale_date BETWEEN p.promo_start AND p.promo_end
"""
GOOD_EXPLODING = f"""
    SELECT f.sale_id, f.revenue, p.promo_id
    FROM {FACT} f
    JOIN {PROMOTIONS} p
      ON f.region = p.region
     AND f.sale_date BETWEEN p.promo_start AND p.promo_end
    WHERE f.sale_date BETWEEN '2024-03-01' AND '2024-03-31'
"""
print(explain_text(spark, BAD_EXPLODING))
bench_query(
    spark, cfg, "query", "exploding_join__bad", BAD_EXPLODING,
    {"case": "exploding_join", "phase": "bad"},
)
print(explain_text(spark, GOOD_EXPLODING))
bench_query(
    spark, cfg, "query", "exploding_join__rewritten", GOOD_EXPLODING,
    {"case": "exploding_join", "phase": "rewritten"},
)

# COMMAND ----------

# MAGIC %md ## Bad query 2 — non-sargable filter kills data skipping
# MAGIC `year()`/`month()` wrap the clustering column so Delta cannot prune files;
# MAGIC the rewrite uses a plain range predicate on the liquid-clustered table.

# COMMAND ----------

BAD_NONSARGABLE = f"""
    SELECT channel, count(*) AS sales, sum(revenue) AS revenue
    FROM {FACT_CLUSTERED}
    WHERE year(sale_date) = 2024 AND month(sale_date) = 6
    GROUP BY channel
"""
GOOD_SARGABLE = f"""
    SELECT channel, count(*) AS sales, sum(revenue) AS revenue
    FROM {FACT_CLUSTERED}
    WHERE sale_date BETWEEN '2024-06-01' AND '2024-06-30'
    GROUP BY channel
"""
print(explain_text(spark, BAD_NONSARGABLE))
bench_query(
    spark, cfg, "query", "nonsargable__bad", BAD_NONSARGABLE,
    {"case": "nonsargable", "phase": "bad"},
)
print(explain_text(spark, GOOD_SARGABLE))
bench_query(
    spark, cfg, "query", "nonsargable__rewritten", GOOD_SARGABLE,
    {"case": "nonsargable", "phase": "rewritten"},
)

# COMMAND ----------

# MAGIC %md ## Bad query 3 — needless DISTINCT on an already-unique key
# MAGIC `sale_id` is unique, so DISTINCT only adds a full-width shuffle + dedup.

# COMMAND ----------

BAD_DISTINCT = f"""
    SELECT DISTINCT f.sale_id, f.quantity, f.revenue, p.brand
    FROM {FACT} f JOIN {PRODUCTS} p USING (product_id)
    WHERE f.sale_date BETWEEN '2024-01-01' AND '2024-06-30'
"""
GOOD_NO_DISTINCT = f"""
    SELECT f.sale_id, f.quantity, f.revenue, p.brand
    FROM {FACT} f JOIN {PRODUCTS} p USING (product_id)
    WHERE f.sale_date BETWEEN '2024-01-01' AND '2024-06-30'
"""
print(explain_text(spark, BAD_DISTINCT))
bench_query(
    spark, cfg, "query", "needless_distinct__bad", BAD_DISTINCT,
    {"case": "needless_distinct", "phase": "bad"},
)
bench_query(
    spark, cfg, "query", "needless_distinct__rewritten", GOOD_NO_DISTINCT,
    {"case": "needless_distinct", "phase": "rewritten"},
)

# COMMAND ----------

# MAGIC %md ## Broadcast vs shuffle join (200-row dimension)

# COMMAND ----------

JOIN_SQL = f"""
    SELECT p.brand, sum(f.revenue) AS revenue
    FROM {FACT} f JOIN {PRODUCTS} p USING (product_id)
    GROUP BY p.brand
"""
default_threshold = spark.conf.get("spark.sql.autoBroadcastJoinThreshold")
spark.conf.set("spark.sql.autoBroadcastJoinThreshold", "-1")
print(explain_text(spark, JOIN_SQL))
bench_query(
    spark, cfg, "query", "dim_join__shuffle_forced", JOIN_SQL,
    {"case": "broadcast_vs_shuffle", "phase": "shuffle", "autoBroadcastJoinThreshold": "-1"},
)
spark.conf.set("spark.sql.autoBroadcastJoinThreshold", default_threshold)
print(explain_text(spark, JOIN_SQL))
bench_query(
    spark, cfg, "query", "dim_join__broadcast", JOIN_SQL,
    {"case": "broadcast_vs_shuffle", "phase": "broadcast",
     "autoBroadcastJoinThreshold": default_threshold},
)

# COMMAND ----------

# MAGIC %md ## AQE on/off under the skewed hot-key join
# MAGIC ~30% of fact rows share one customer_id; AQE's skew-join splitting and
# MAGIC coalescing are the difference under measurement.

# COMMAND ----------

SKEW_SQL = f"""
    SELECT c.segment, count(*) AS sales, sum(f.revenue) AS revenue
    FROM {FACT} f JOIN {CUSTOMERS} c USING (customer_id)
    GROUP BY c.segment
"""
spark.conf.set("spark.sql.adaptive.enabled", "false")
spark.conf.set("spark.sql.autoBroadcastJoinThreshold", "-1")  # keep it a shuffle join
bench_query(
    spark, cfg, "query", "skew_join__aqe_off", SKEW_SQL, {"case": "aqe_skew", "phase": "aqe_off"}
)
spark.conf.set("spark.sql.adaptive.enabled", "true")
bench_query(
    spark, cfg, "query", "skew_join__aqe_on", SKEW_SQL, {"case": "aqe_skew", "phase": "aqe_on"}
)
spark.conf.set("spark.sql.autoBroadcastJoinThreshold", default_threshold)

log_run(spark, cfg, task="perf_query_lab", status="succeeded", started_at=started)
print("query lab complete")
