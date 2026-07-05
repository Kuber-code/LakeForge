"""Benchmark harness — every measured run lands in ``ops.benchmarks``.

One row per measurement: category (cluster/layout/query/maintenance),
experiment name, free-form config map, metrics map, and wall-clock duration.
Queries are executed ``runs`` times; the recorded duration is the median of
the warm runs so a cold first execution does not dominate the comparison.
"""

from __future__ import annotations

import statistics
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from pyspark.sql import DataFrame, Row, SparkSession

from lakeforge.config import LakeforgeConfig

_BENCHMARKS_DDL = """
    bench_id      STRING NOT NULL,
    ts            TIMESTAMP NOT NULL,
    category      STRING NOT NULL,
    name          STRING NOT NULL,
    config        MAP<STRING, STRING>,
    metrics       MAP<STRING, STRING>,
    duration_ms   BIGINT NOT NULL
"""


def ensure_benchmarks_table(spark: SparkSession, cfg: LakeforgeConfig) -> None:
    spark.sql(f"CREATE TABLE IF NOT EXISTS {cfg.table('ops', 'benchmarks')} ({_BENCHMARKS_DDL})")


def record(
    spark: SparkSession,
    cfg: LakeforgeConfig,
    category: str,
    name: str,
    duration_ms: int,
    config: dict[str, str] | None = None,
    metrics: dict[str, str] | None = None,
) -> str:
    bench_id = str(uuid.uuid4())
    target = cfg.table("ops", "benchmarks")
    row = Row(
        bench_id=bench_id,
        ts=datetime.now(UTC),
        category=category,
        name=name,
        config={k: str(v) for k, v in (config or {}).items()},
        metrics={k: str(v) for k, v in (metrics or {}).items()},
        duration_ms=duration_ms,
    )
    schema = spark.table(target).schema
    spark.createDataFrame([row], schema=schema).write.mode("append").saveAsTable(target)
    return bench_id


def timed(fn: Callable[[], object]) -> tuple[int, object]:
    """Wall-clock one call; returns (millis, fn result)."""
    start = time.perf_counter()
    result = fn()
    return int((time.perf_counter() - start) * 1000), result


def bench_query(
    spark: SparkSession,
    cfg: LakeforgeConfig,
    category: str,
    name: str,
    sql: str,
    config: dict[str, str] | None = None,
    runs: int = 3,
) -> int:
    """Run ``sql`` ``runs`` times; record median warm duration + cold time.

    The action is a full materialization (collect of the aggregated result or
    count for wide results) so lazy execution cannot fake instant queries.
    """
    durations: list[int] = []
    rows_out: object = 0
    for _ in range(runs):
        ms, rows_out = timed(lambda: _materialize(spark.sql(sql)))
        durations.append(ms)
    warm = durations[1:] or durations
    median_warm = int(statistics.median(warm))
    record(
        spark,
        cfg,
        category=category,
        name=name,
        duration_ms=median_warm,
        config=config,
        metrics={
            "cold_ms": durations[0],
            "all_runs_ms": ",".join(str(d) for d in durations),
            "rows_out": rows_out,
            "sql": " ".join(sql.split())[:500],
        },
    )
    return median_warm


def _materialize(df: DataFrame) -> int:
    return df.count()


def table_stats(spark: SparkSession, fq_table: str) -> dict[str, str]:
    """numFiles / sizeInBytes / clustering from DESCRIBE DETAIL."""
    detail = spark.sql(f"DESCRIBE DETAIL {fq_table}").collect()[0]
    return {
        "num_files": str(detail["numFiles"]),
        "size_bytes": str(detail["sizeInBytes"]),
        "partition_columns": ",".join(detail["partitionColumns"] or []),
        "clustering_columns": ",".join(detail["clusteringColumns"] or []),
    }


def explain_text(spark: SparkSession, sql: str) -> str:
    """FORMATTED plan for before/after evidence in the findings doc."""
    return spark.sql(f"EXPLAIN FORMATTED {sql}").collect()[0][0]
