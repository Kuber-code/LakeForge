# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze — incremental JDBC extract from Azure SQL (FR-4.2)
# MAGIC Credentials come from the Key Vault-backed secret scope (FR-2.4);
# MAGIC no secret value ever appears here, only scope/key references.

# COMMAND ----------

import os
import sys
from datetime import UTC, datetime

sys.path.append(os.path.abspath("../src"))

from lakeforge.config import SQL_SOURCES, for_env
from lakeforge.ingest.sql import JdbcSource, run_bronze_sql
from lakeforge.ops import ensure_ops_tables, log_run

dbutils.widgets.text("env", "dev")
dbutils.widgets.text("storage_account", "stlakeforgedevsh93zt")

cfg = for_env(dbutils.widgets.get("env"), dbutils.widgets.get("storage_account"))
ensure_ops_tables(spark, cfg)

jdbc = JdbcSource(
    url=dbutils.secrets.get(cfg.secret_scope, "sql-jdbc-url"),
    user=dbutils.secrets.get(cfg.secret_scope, "sql-admin-login"),
    password=dbutils.secrets.get(cfg.secret_scope, "sql-admin-password"),
)

# COMMAND ----------

for table in SQL_SOURCES:
    started = datetime.now(UTC)
    metrics = run_bronze_sql(spark, cfg, jdbc, table)
    log_run(
        spark,
        cfg,
        task=f"bronze_sql_{table}",
        status="succeeded",
        started_at=started,
        metrics=metrics,
    )
    print(metrics)
