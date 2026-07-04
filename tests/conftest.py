"""Shared local-Spark fixtures: Delta-enabled session + isolated schemas.

Tests run against plain ``spark_catalog`` with the same schema names the
pipelines use in Unity Catalog, so production code paths are exercised
verbatim (only the catalog differs).
"""

from __future__ import annotations

import shutil
import tempfile

import pytest
from delta import configure_spark_with_delta_pip
from pyspark.sql import SparkSession

from lakeforge.config import LakeforgeConfig

SCHEMAS = ("bronze", "silver", "gold", "ops")


@pytest.fixture(scope="session")
def spark():
    warehouse = tempfile.mkdtemp(prefix="lakeforge-warehouse-")
    builder = (
        SparkSession.builder.master("local[2]")
        .appName("lakeforge-tests")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        .config("spark.sql.warehouse.dir", warehouse)
        # Databricks defaults to Delta for saveAsTable / CREATE TABLE; local
        # Spark defaults to parquet, so align it here.
        .config("spark.sql.sources.default", "delta")
        .config("spark.sql.legacy.createHiveTableByDefault", "false")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.databricks.delta.snapshotPartitions", "2")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.session.timeZone", "UTC")
    )
    session = configure_spark_with_delta_pip(builder).getOrCreate()
    yield session
    session.stop()
    shutil.rmtree(warehouse, ignore_errors=True)


@pytest.fixture()
def cfg(spark) -> LakeforgeConfig:
    """Fresh bronze/silver/gold/ops schemas for every test."""
    for schema in SCHEMAS:
        spark.sql(f"DROP DATABASE IF EXISTS {schema} CASCADE")
        spark.sql(f"CREATE DATABASE {schema}")
    return LakeforgeConfig(env="test", catalog="spark_catalog")
