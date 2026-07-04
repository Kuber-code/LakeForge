# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze — distributor file drops (FR-4.1)
# MAGIC Thin entry point: Auto Loader ingest of `shipments/*.csv` and
# MAGIC `returns/*.json` from the landing volume into bronze tables.

# COMMAND ----------

import os
import sys
from datetime import UTC, datetime

sys.path.append(os.path.abspath("../src"))

from lakeforge.config import FILE_SOURCES, for_env
from lakeforge.ingest.files import run_bronze_files
from lakeforge.ops import ensure_ops_tables, log_run

dbutils.widgets.text("env", "dev")
dbutils.widgets.text("storage_account", "stlakeforgedevsh93zt")

cfg = for_env(dbutils.widgets.get("env"), dbutils.widgets.get("storage_account"))
ensure_ops_tables(spark, cfg)

# COMMAND ----------

for source in FILE_SOURCES:
    started = datetime.now(UTC)
    rows = run_bronze_files(spark, cfg, source)
    log_run(
        spark,
        cfg,
        task=f"bronze_files_{source}",
        status="succeeded",
        started_at=started,
        metrics={"rows_ingested": rows},
    )
    print(f"{source}: {rows} rows ingested")
