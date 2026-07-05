"""FR-4.1 — bronze ingestion of distributor file drops with Auto Loader.

Each source subfolder of the landing volume (``shipments/*.csv``,
``returns/*.json``) streams into its own bronze table. Schema evolution is
on (``addNewColumns``), malformed fields land in ``_rescued_data``, and every
row carries ``_ingest_ts`` / ``_source_file`` load metadata. Checkpoints (and
Auto Loader's schema tracking) live in the ``checkpoints`` container, so a
re-run resumes exactly where it stopped instead of re-reading files (FR-4.6).

``with_ingest_metadata`` is a pure transformation so the metadata contract is
unit-testable without cloudFiles (which only exists on Databricks).
"""

from __future__ import annotations

import os

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from lakeforge.config import FILE_SOURCES, LakeforgeConfig


def landing_has_files(path: str) -> bool:
    """True when at least one file exists under ``path`` (recursively).

    Auto Loader cannot infer a schema from an empty directory
    (CF_EMPTY_DIR_FOR_SCHEMA_INFERENCE) — first observed on the very first
    prod cron run, whose landing volume had no distributor drops yet. Landing
    volumes are FUSE-mounted (/Volumes/...) and tests use local paths, so a
    plain filesystem walk covers both.
    """
    if not os.path.isdir(path):
        return False
    return any(files for _, _, files in os.walk(path))


def with_ingest_metadata(df: DataFrame) -> DataFrame:
    """Stamp the bronze load-metadata columns onto a raw dataframe."""
    return df.withColumns(
        {
            "_ingest_ts": F.current_timestamp(),
            "_source_file": F.col("_metadata.file_path"),
        }
    )


def bronze_files_stream(
    spark: SparkSession, cfg: LakeforgeConfig, source: str
) -> tuple[DataFrame, str, str]:
    """Configured Auto Loader stream for one landing source.

    Returns (stream_df, target_table, checkpoint_path); the caller starts it
    with ``trigger(availableNow=True)`` for batch-style manual runs (P2) or a
    file-arrival trigger later (FR-5.2).
    """
    fmt = FILE_SOURCES[source]
    checkpoint = cfg.checkpoint_path(f"bronze_{source}")

    reader = (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", fmt)
        .option("cloudFiles.schemaLocation", checkpoint)
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
        .option("rescuedDataColumn", "_rescued_data")
    )
    if fmt == "csv":
        reader = reader.option("header", "true")

    stream = with_ingest_metadata(reader.load(cfg.landing_path(source)))
    return stream, cfg.table("bronze", source), checkpoint


def run_bronze_files(spark: SparkSession, cfg: LakeforgeConfig, source: str) -> int:
    """Ingest all currently available files for one source; returns rows written.

    An empty (or missing) landing folder is a normal day, not an error: the
    run reports 0 rows and downstream layers proceed on existing bronze.
    """
    if not landing_has_files(cfg.landing_path(source)):
        print(f"landing path {cfg.landing_path(source)} is empty; skipping {source}")
        return 0
    stream, target, checkpoint = bronze_files_stream(spark, cfg, source)
    query = (
        stream.writeStream.format("delta")
        .option("checkpointLocation", checkpoint)
        .option("mergeSchema", "true")
        .trigger(availableNow=True)
        .toTable(target)
    )
    query.awaitTermination()
    progress = query.lastProgress
    return int(progress["sink"]["numOutputRows"]) if progress else 0
