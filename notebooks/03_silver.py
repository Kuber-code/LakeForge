# Databricks notebook source
# MAGIC %md
# MAGIC # Silver — conformance, SCD2, CDF (FR-4.3)

# COMMAND ----------

import os
import sys
from datetime import UTC, datetime

sys.path.append(os.path.abspath("../src"))

from lakeforge.config import for_env
from lakeforge.ops import ensure_ops_tables, log_run
from lakeforge.transform.silver import run_silver

dbutils.widgets.text("env", "dev")
dbutils.widgets.text("storage_account", "stlakeforgedevsh93zt")

cfg = for_env(dbutils.widgets.get("env"), dbutils.widgets.get("storage_account"))
ensure_ops_tables(spark, cfg)

# COMMAND ----------

started = datetime.now(UTC)
metrics = run_silver(spark, cfg)
log_run(spark, cfg, task="silver", status="succeeded", started_at=started, metrics=metrics)
print(metrics)

# FR-5.3 — the job's conditional task reads this to skip gold when nothing changed.
dbutils.jobs.taskValues.set("rows_changed", int(metrics["rows_changed"]))
