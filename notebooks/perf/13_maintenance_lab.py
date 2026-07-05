# Databricks notebook source
# MAGIC %md
# MAGIC # Perf lab — Delta maintenance: VACUUM, time travel, history (FR-7.5)
# MAGIC
# MAGIC Works on a dedicated 1M-row copy so history stunts never touch the
# MAGIC benchmark tables. Demonstrates DESCRIBE HISTORY forensics, time travel,
# MAGIC RESTORE, and the VACUUM retention trade-off.

# COMMAND ----------

import os
import sys
from datetime import UTC, datetime

sys.path.append(os.path.abspath("../../src"))

from lakeforge.config import for_env
from lakeforge.ops import log_run
from lakeforge.perf.bench import ensure_benchmarks_table, record, timed
from lakeforge.perf.generator import PERF_SCHEMA, ensure_perf_schema, synthetic_sales

dbutils.widgets.text("env", "dev")
dbutils.widgets.text("storage_account", "stlakeforgedevsh93zt")

cfg = for_env(dbutils.widgets.get("env"), dbutils.widgets.get("storage_account"))
ensure_perf_schema(spark, cfg)
ensure_benchmarks_table(spark, cfg)

T = cfg.table(PERF_SCHEMA, "fact_maintenance")
started = datetime.now(UTC)

# COMMAND ----------

# MAGIC %md ## Build some history: create → update → delete → compact

# COMMAND ----------

synthetic_sales(spark, 1_000_000).write.mode("overwrite").option(
    "overwriteSchema", "true"
).saveAsTable(T)                                                        # v0/v1
spark.sql(f"UPDATE {T} SET quantity = quantity + 1 WHERE channel = 'export'")   # +1 version
spark.sql(f"DELETE FROM {T} WHERE customer_id = 13")                             # +1 version
spark.sql(f"OPTIMIZE {T}")                                                       # +1 version

history = spark.sql(f"DESCRIBE HISTORY {T}")
display(history.select("version", "timestamp", "operation", "operationMetrics"))
versions = [r["version"] for r in history.select("version").collect()]
v_first, v_latest = min(versions), max(versions)

# COMMAND ----------

# MAGIC %md ## Time travel — read the pre-UPDATE state and diff it

# COMMAND ----------

ms, before_count = timed(
    lambda: spark.sql(f"SELECT count(*) c FROM {T} VERSION AS OF {v_first}").collect()[0]["c"]
)
now_count = spark.table(T).count()
record(
    spark, cfg, "maintenance", "time_travel_read", ms,
    config={"table": T, "version": v_first},
    metrics={"rows_at_v0": before_count, "rows_now": now_count,
             "deleted_rows_visible_at_v0": before_count - now_count},
)
print(f"v{v_first}: {before_count} rows, current: {now_count} rows ({ms} ms)")

# RESTORE forensics demo: bring the deleted customer back, then verify
spark.sql(f"RESTORE TABLE {T} TO VERSION AS OF {v_first + 1}")
print("after RESTORE:", spark.table(T).count())

# COMMAND ----------

# MAGIC %md ## VACUUM — retention trade-offs
# MAGIC Default retention is 7 days: a fresh table has nothing eligible, which is
# MAGIC exactly the safety story. Forcing `RETAIN 0 HOURS` (with the guard off)
# MAGIC reclaims every stale file — and severs time travel to older versions.

# COMMAND ----------

dry_default = spark.sql(f"VACUUM {T} DRY RUN").collect()
print(f"eligible files at 7-day retention: {len(dry_default)}")

spark.conf.set("spark.databricks.delta.retentionDurationCheck.enabled", "false")
dry_zero = spark.sql(f"VACUUM {T} RETAIN 0 HOURS DRY RUN").collect()
ms, _ = timed(lambda: spark.sql(f"VACUUM {T} RETAIN 0 HOURS"))
spark.conf.set("spark.databricks.delta.retentionDurationCheck.enabled", "true")

time_travel_broken = False
try:
    spark.sql(f"SELECT count(*) FROM {T} VERSION AS OF {v_first}").collect()
except Exception as exc:  # noqa: BLE001 — the failure IS the demonstration
    time_travel_broken = True
    print(f"time travel to v{v_first} now fails as expected: {type(exc).__name__}")

record(
    spark, cfg, "maintenance", "vacuum_retention_tradeoff", ms,
    config={"table": T, "retain_hours": 0},
    metrics={"files_eligible_7d": len(dry_default), "files_eligible_0h": len(dry_zero),
             "time_travel_broken_after": time_travel_broken},
)

log_run(spark, cfg, task="perf_maintenance_lab", status="succeeded", started_at=started)
print("maintenance lab complete")
