"""Operational state tables in the ``ops`` schema (FR-3.5, FR-4.2, FR-4.5).

``ops.watermarks``     — high-water mark per JDBC source table.
``ops.pipeline_runs``  — one row per task execution with metrics and status.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pyspark.sql import Row, SparkSession
from pyspark.sql import functions as F

from lakeforge.config import LakeforgeConfig

# Epoch start used when a source has no watermark yet (first full extract).
INITIAL_WATERMARK = datetime(1900, 1, 1)

_WATERMARKS_DDL = """
    source        STRING NOT NULL,
    watermark     TIMESTAMP NOT NULL,
    updated_at    TIMESTAMP NOT NULL
"""

_PIPELINE_RUNS_DDL = """
    run_id        STRING NOT NULL,
    task          STRING NOT NULL,
    status        STRING NOT NULL,
    started_at    TIMESTAMP NOT NULL,
    finished_at   TIMESTAMP,
    metrics       MAP<STRING, STRING>,
    message       STRING
"""


def ensure_ops_tables(spark: SparkSession, cfg: LakeforgeConfig) -> None:
    """Idempotent DDL for the ops tables (NFR-5)."""
    spark.sql(f"CREATE TABLE IF NOT EXISTS {cfg.table('ops', 'watermarks')} ({_WATERMARKS_DDL})")
    spark.sql(
        f"CREATE TABLE IF NOT EXISTS {cfg.table('ops', 'pipeline_runs')} ({_PIPELINE_RUNS_DDL})"
    )


def get_watermark(spark: SparkSession, cfg: LakeforgeConfig, source: str) -> datetime:
    rows = (
        spark.table(cfg.table("ops", "watermarks"))
        .where(F.col("source") == source)
        .select("watermark")
        .collect()
    )
    return rows[0]["watermark"] if rows else INITIAL_WATERMARK


def set_watermark(
    spark: SparkSession, cfg: LakeforgeConfig, source: str, watermark: datetime
) -> None:
    """Upsert the high-water mark for one source (re-runnable)."""
    target = cfg.table("ops", "watermarks")
    update = spark.createDataFrame(
        [Row(source=source, watermark=watermark, updated_at=datetime.now(UTC))]
    )
    update.createOrReplaceTempView("_watermark_update")
    spark.sql(
        f"""
        MERGE INTO {target} t
        USING _watermark_update s
        ON t.source = s.source
        WHEN MATCHED THEN UPDATE SET t.watermark = s.watermark, t.updated_at = s.updated_at
        WHEN NOT MATCHED THEN INSERT *
        """
    )


def log_run(
    spark: SparkSession,
    cfg: LakeforgeConfig,
    task: str,
    status: str,
    started_at: datetime,
    metrics: dict[str, str] | None = None,
    message: str | None = None,
    run_id: str | None = None,
) -> str:
    """Append one execution record to ops.pipeline_runs; returns the run id."""
    run_id = run_id or str(uuid.uuid4())
    row = Row(
        run_id=run_id,
        task=task,
        status=status,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        metrics={k: str(v) for k, v in (metrics or {}).items()},
        message=message,
    )
    schema = spark.table(cfg.table("ops", "pipeline_runs")).schema
    spark.createDataFrame([row], schema=schema).write.mode("append").saveAsTable(
        cfg.table("ops", "pipeline_runs")
    )
    return run_id
