"""FR-4.2 — incremental JDBC extraction from Azure SQL into bronze.

Each source table is pulled with ``modified_at > watermark`` (the watermark
lives in ``ops.watermarks``), stamped with load metadata, and merged into its
bronze table on ``(primary key, modified_at)``. Using MERGE instead of a blind
append keeps bronze append-only in spirit (every source-row *version* is kept
for SCD2) while making a re-run of the same increment a no-op (FR-4.6).

Credentials come from the Key Vault-backed secret scope and are passed in by
the entry-point notebook; this module never touches dbutils (FR-2.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from lakeforge.config import SQL_SOURCES, LakeforgeConfig
from lakeforge.ops import get_watermark, set_watermark


@dataclass(frozen=True)
class JdbcSource:
    url: str
    user: str
    password: str

    def read_increment(self, spark: SparkSession, table: str, watermark: datetime) -> DataFrame:
        # Pushdown query so Azure SQL only ships changed rows.
        query = (
            f"SELECT * FROM dbo.{table} "
            f"WHERE modified_at > '{watermark.isoformat(sep=' ', timespec='microseconds')}'"
        )
        return (
            spark.read.format("jdbc")
            .option("url", self.url)
            .option("query", query)
            .option("user", self.user)
            .option("password", self.password)
            .option("driver", "com.microsoft.sqlserver.jdbc.SQLServerDriver")
            .load()
        )


def with_load_metadata(df: DataFrame, source_table: str) -> DataFrame:
    """Stamp bronze load-metadata columns onto a JDBC increment."""
    return df.withColumns(
        {
            "_ingest_ts": F.current_timestamp(),
            "_source_system": F.lit("azure_sql"),
            "_source_table": F.lit(f"dbo.{source_table}"),
        }
    )


def merge_increment(
    spark: SparkSession, cfg: LakeforgeConfig, table: str, increment: DataFrame
) -> int:
    """Idempotent write of one increment into bronze; returns rows in increment.

    Keyed on (pk, modified_at): a new version of a row inserts a new bronze
    row; re-processing the same increment matches and changes nothing.
    """
    pk = SQL_SOURCES[table]
    target = cfg.table("bronze", table)

    if not spark.catalog.tableExists(target):
        increment.limit(0).write.saveAsTable(target)

    increment.createOrReplaceTempView("_bronze_increment")
    spark.sql(
        f"""
        MERGE INTO {target} t
        USING _bronze_increment s
        ON t.{pk} = s.{pk} AND t.modified_at = s.modified_at
        WHEN NOT MATCHED THEN INSERT *
        """
    )
    return increment.count()


def run_bronze_sql(
    spark: SparkSession, cfg: LakeforgeConfig, jdbc: JdbcSource, table: str
) -> dict[str, str]:
    """Extract one table incrementally; advances the watermark on success."""
    watermark = get_watermark(spark, cfg, table)
    increment = with_load_metadata(jdbc.read_increment(spark, table, watermark), table)
    # The increment is read twice (merge + max watermark); keep it stable.
    increment = increment.cache()

    rows = merge_increment(spark, cfg, table, increment)
    new_watermark = increment.agg(F.max("modified_at")).collect()[0][0]
    if new_watermark is not None:
        set_watermark(spark, cfg, table, new_watermark)

    increment.unpersist()
    return {
        "table": table,
        "rows": str(rows),
        "watermark_before": watermark.isoformat(),
        "watermark_after": (new_watermark or watermark).isoformat(),
    }
