# Databricks notebook source
# MAGIC %md
# MAGIC # Gold — star schema + aggregates, then quality gates (FR-4.4, FR-4.5)

# COMMAND ----------

import os
import sys
from datetime import UTC, datetime

sys.path.append(os.path.abspath("../src"))

from lakeforge.config import for_env
from lakeforge.ops import ensure_ops_tables, log_run
from lakeforge.quality.gates import run_gates, standard_gates
from lakeforge.transform.gold import run_gold

dbutils.widgets.text("env", "dev")
dbutils.widgets.text("storage_account", "stlakeforgedevsh93zt")

cfg = for_env(dbutils.widgets.get("env"), dbutils.widgets.get("storage_account"))
ensure_ops_tables(spark, cfg)

# COMMAND ----------

started = datetime.now(UTC)
metrics = run_gold(spark, cfg)
log_run(spark, cfg, task="gold", status="succeeded", started_at=started, metrics=metrics)
print(metrics)

# COMMAND ----------

# FR-4.5 — gates raise (failing the job) if any check is violated.
run_gates(spark, cfg, standard_gates(spark, cfg))
print("all quality gates passed")
