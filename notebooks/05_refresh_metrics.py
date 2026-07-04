# Databricks notebook source
# MAGIC %md
# MAGIC # Refresh metrics — freshness per layer into ops (FR-3.5, feeds FR-8.2)
# MAGIC Runs after gold: records data freshness for each layer so the P4
# MAGIC operations dashboard (and the gold-freshness alert, FR-8.4) can read it.

# COMMAND ----------

import os
import sys
from datetime import UTC, datetime

sys.path.append(os.path.abspath("../src"))

from lakeforge.config import for_env
from lakeforge.ops import ensure_ops_tables, log_run

dbutils.widgets.text("env", "dev")
dbutils.widgets.text("storage_account", "stlakeforgedevsh93zt")

cfg = for_env(dbutils.widgets.get("env"), dbutils.widgets.get("storage_account"))
ensure_ops_tables(spark, cfg)

# COMMAND ----------

started = datetime.now(UTC)
freshness: dict[str, str] = {}
probes = {
    "bronze": ("orders", "max(_ingest_ts)"),
    "silver": ("orders", "max(_ingest_ts)"),
    "gold": ("fact_sales", "max(order_date)"),
}
for layer, (table, expr) in probes.items():
    value = spark.sql(f"SELECT {expr} FROM {cfg.table(layer, table)}").collect()[0][0]
    freshness[f"{layer}_freshness"] = str(value)

log_run(
    spark,
    cfg,
    task="refresh_metrics",
    status="succeeded",
    started_at=started,
    metrics=freshness,
)
print(freshness)
