# Databricks notebook source
# MAGIC %md
# MAGIC # Perf lab — generate the synthetic fact + layout variants (FR-7.1, FR-7.3 setup)
# MAGIC
# MAGIC Builds `perf.fact_source` (50M rows by default) and the five physical
# MAGIC layout variants the layout lab measures. Deterministic and idempotent —
# MAGIC re-running rebuilds identical tables.

# COMMAND ----------

import os
import sys
from datetime import UTC, datetime

sys.path.append(os.path.abspath("../../src"))

from lakeforge.config import for_env
from lakeforge.ops import ensure_ops_tables, log_run
from lakeforge.perf.bench import ensure_benchmarks_table, record, table_stats, timed
from lakeforge.perf.generator import write_layout_variants

dbutils.widgets.text("env", "dev")
dbutils.widgets.text("storage_account", "stlakeforgedevsh93zt")
dbutils.widgets.text("rows", "50000000")

cfg = for_env(dbutils.widgets.get("env"), dbutils.widgets.get("storage_account"))
rows = int(dbutils.widgets.get("rows"))
ensure_ops_tables(spark, cfg)
ensure_benchmarks_table(spark, cfg)

# COMMAND ----------

started = datetime.now(UTC)
gen_ms, variants = timed(lambda: write_layout_variants(spark, cfg, rows))

for variant, table in variants.items():
    stats = table_stats(spark, table)
    record(
        spark,
        cfg,
        category="layout",
        name=f"stats_{variant}",
        duration_ms=0,
        config={"table": table, "rows": rows},
        metrics=stats,
    )
    print(variant, stats)

log_run(
    spark,
    cfg,
    task="perf_generate",
    status="succeeded",
    started_at=started,
    metrics={"rows": str(rows), "generate_ms": str(gen_ms), "variants": str(len(variants))},
)
print(f"generated {rows} rows + {len(variants)} layout variants in {gen_ms} ms")
