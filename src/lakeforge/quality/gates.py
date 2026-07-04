"""FR-4.5 — lightweight quality gates logged to ops.pipeline_runs.

Deliberately minimal (row counts, PK uniqueness, null thresholds): deep data
quality is BrewQuality's job, and the docs say so. A failed gate raises after
all gates have been evaluated, so one run reports every violation at once.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from lakeforge.config import LakeforgeConfig
from lakeforge.ops import log_run


@dataclass(frozen=True)
class GateResult:
    gate: str
    table: str
    passed: bool
    observed: str
    expected: str

    def as_metric(self) -> tuple[str, str]:
        status = "pass" if self.passed else "FAIL"
        return (
            f"{self.gate}:{self.table}",
            f"{status} observed={self.observed} expected={self.expected}",
        )


class QualityGateError(Exception):
    """At least one quality gate failed."""


def row_count_min(df: DataFrame, table: str, minimum: int) -> GateResult:
    n = df.count()
    return GateResult("row_count_min", table, n >= minimum, str(n), f">={minimum}")


def pk_unique(df: DataFrame, table: str, pk: str) -> GateResult:
    dupes = df.groupBy(pk).count().where("count > 1").count()
    return GateResult("pk_unique", table, dupes == 0, f"{dupes} duplicate keys", "0")


def null_ratio_max(df: DataFrame, table: str, column: str, threshold: float) -> GateResult:
    total = df.count()
    nulls = df.where(F.col(column).isNull()).count()
    ratio = nulls / total if total else 0.0
    return GateResult(
        "null_ratio_max", f"{table}.{column}", ratio <= threshold, f"{ratio:.4f}", f"<={threshold}"
    )


def run_gates(
    spark: SparkSession,
    cfg: LakeforgeConfig,
    results: list[GateResult],
    task: str = "quality_gates",
) -> None:
    """Log all gate outcomes to ops.pipeline_runs; raise if any failed."""
    started = datetime.now(UTC)
    failed = [r for r in results if not r.passed]
    log_run(
        spark,
        cfg,
        task=task,
        status="failed" if failed else "succeeded",
        started_at=started,
        metrics=dict(r.as_metric() for r in results),
        message=f"{len(failed)} of {len(results)} gates failed" if failed else None,
    )
    if failed:
        detail = "; ".join(f"{r.gate}({r.table})" for r in failed)
        raise QualityGateError(f"Quality gates failed: {detail}")


def standard_gates(spark: SparkSession, cfg: LakeforgeConfig) -> list[GateResult]:
    """The default gate set run after each silver+gold refresh."""
    silver_orders = spark.table(cfg.table("silver", "orders"))
    silver_customers = spark.table(cfg.table("silver", "customers"))
    fact_sales = spark.table(cfg.table("gold", "fact_sales"))

    current_customers = silver_customers.where("is_current = true")
    return [
        row_count_min(silver_orders, "silver.orders", 1),
        row_count_min(fact_sales, "gold.fact_sales", 1),
        pk_unique(silver_orders, "silver.orders", "order_id"),
        pk_unique(current_customers, "silver.customers[current]", "customer_id"),
        pk_unique(fact_sales, "gold.fact_sales", "order_line_id"),
        null_ratio_max(fact_sales, "gold.fact_sales", "customer_sk", 0.0),
        null_ratio_max(fact_sales, "gold.fact_sales", "product_sk", 0.01),
    ]
