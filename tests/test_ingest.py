from datetime import datetime

from pyspark.sql import functions as F

from lakeforge.config import LakeforgeConfig
from lakeforge.ingest.files import landing_has_files, run_bronze_files
from lakeforge.ingest.sql import merge_increment, with_load_metadata

T0 = datetime(2026, 7, 1, 10, 0, 0)
T1 = datetime(2026, 7, 2, 10, 0, 0)

SCHEMA = "order_id INT, status STRING, modified_at TIMESTAMP"


def test_with_load_metadata_stamps_columns(spark):
    df = with_load_metadata(spark.createDataFrame([(1, "placed", T0)], SCHEMA), "orders")
    row = df.collect()[0]
    assert row["_source_system"] == "azure_sql"
    assert row["_source_table"] == "dbo.orders"
    assert row["_ingest_ts"] is not None


def test_merge_increment_keeps_versions_and_is_idempotent(spark, cfg):
    inc1 = with_load_metadata(spark.createDataFrame([(1, "placed", T0)], SCHEMA), "orders")
    merge_increment(spark, cfg, "orders", inc1)
    # Re-run of the same increment: no duplicates (FR-4.6).
    merge_increment(spark, cfg, "orders", inc1)
    assert spark.table(cfg.table("bronze", "orders")).count() == 1

    # A new version of the same order is a NEW bronze row (history for SCD2).
    inc2 = with_load_metadata(spark.createDataFrame([(1, "delivered", T1)], SCHEMA), "orders")
    merge_increment(spark, cfg, "orders", inc2)
    bronze = spark.table(cfg.table("bronze", "orders"))
    assert bronze.count() == 2
    assert bronze.where(F.col("status") == "delivered").count() == 1


def test_landing_has_files(tmp_path):
    assert not landing_has_files(str(tmp_path / "missing"))
    (tmp_path / "shipments").mkdir()
    assert not landing_has_files(str(tmp_path / "shipments"))
    nested = tmp_path / "shipments" / "2026" / "07"
    nested.mkdir(parents=True)
    (nested / "drop.csv").write_text("a,b\n1,2\n")
    assert landing_has_files(str(tmp_path / "shipments"))


def test_run_bronze_files_skips_empty_landing(spark, tmp_path):
    # The first prod cron run failed on exactly this: Auto Loader cannot
    # infer a schema from an empty landing dir. An empty day must be 0 rows,
    # not a job failure.
    cfg = LakeforgeConfig(env="test", catalog="spark_catalog", landing_root=str(tmp_path))
    assert run_bronze_files(spark, cfg, "shipments") == 0
