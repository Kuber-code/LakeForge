# Databricks notebook source
# MAGIC %md
# MAGIC # Perf lab — cluster experiments (FR-7.2)
# MAGIC
# MAGIC The *same* three-part workload runs on each cluster variant (the variant
# MAGIC is defined by the job cluster this task runs on; the `variant` widget only
# MAGIC labels the rows). DBU and VM cost per variant are joined later from
# MAGIC `system.billing.usage` via the `perf_variant` cluster tag.

# COMMAND ----------

import os
import sys
from datetime import UTC, datetime

sys.path.append(os.path.abspath("../../src"))

from lakeforge.config import for_env
from lakeforge.ops import log_run
from lakeforge.perf.bench import bench_query, ensure_benchmarks_table
from lakeforge.perf.generator import PERF_SCHEMA

dbutils.widgets.text("env", "dev")
dbutils.widgets.text("storage_account", "stlakeforgedevsh93zt")
dbutils.widgets.text("variant", "unlabeled")

cfg = for_env(dbutils.widgets.get("env"), dbutils.widgets.get("storage_account"))
variant = dbutils.widgets.get("variant")
ensure_benchmarks_table(spark, cfg)

FACT = cfg.table(PERF_SCHEMA, "fact_compacted")
CUSTOMERS = cfg.table(PERF_SCHEMA, "dim_customer")

cluster_conf = {
    "variant": variant,
    "cluster_id": spark.conf.get("spark.databricks.clusterUsageTags.clusterId", "?"),
    "node_type": spark.conf.get("spark.databricks.clusterUsageTags.clusterNodeType", "?"),
    "workers": spark.conf.get("spark.databricks.clusterUsageTags.clusterWorkers", "?"),
    "runtime": spark.conf.get("spark.databricks.clusterUsageTags.sparkVersion", "?"),
}
print(cluster_conf)

# COMMAND ----------

started = datetime.now(UTC)
WORKLOAD = {
    # CPU + scan bound: full 50M-row aggregation
    "w1_full_scan_agg": f"""
        SELECT region, channel, count(*) AS sales, sum(revenue) AS revenue,
               avg(quantity) AS avg_qty
        FROM {FACT} GROUP BY region, channel
    """,
    # shuffle bound: skewed join + wide aggregation
    "w2_skewed_join": f"""
        SELECT c.segment, c.region, count(*) AS sales, sum(f.revenue) AS revenue
        FROM {FACT} f JOIN {CUSTOMERS} c USING (customer_id)
        GROUP BY c.segment, c.region
    """,
    # skipping bound: selective read
    "w3_selective": f"""
        SELECT sale_date, sum(revenue) AS revenue
        FROM {FACT}
        WHERE customer_id = 4711 AND sale_date >= '2024-01-01'
        GROUP BY sale_date
    """,
}

for name, sql in WORKLOAD.items():
    ms = bench_query(
        spark, cfg, category="cluster", name=f"{name}__{variant}", sql=sql,
        config={**cluster_conf, "workload": name},
    )
    print(f"{variant:20s} {name:20s} {ms} ms")

log_run(
    spark, cfg, task="perf_cluster_probe", status="succeeded", started_at=started,
    metrics=cluster_conf,
)
print("cluster probe complete:", variant)
