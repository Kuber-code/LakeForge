from datetime import UTC, datetime

from lakeforge.ops import (
    INITIAL_WATERMARK,
    ensure_ops_tables,
    get_watermark,
    log_run,
    set_watermark,
)


def test_ensure_ops_tables_is_idempotent(spark, cfg):
    ensure_ops_tables(spark, cfg)
    ensure_ops_tables(spark, cfg)
    assert spark.catalog.tableExists(cfg.table("ops", "watermarks"))
    assert spark.catalog.tableExists(cfg.table("ops", "pipeline_runs"))


def test_watermark_roundtrip(spark, cfg):
    ensure_ops_tables(spark, cfg)
    assert get_watermark(spark, cfg, "orders") == INITIAL_WATERMARK

    first = datetime(2026, 7, 1, 12, 0, 0)
    set_watermark(spark, cfg, "orders", first)
    assert get_watermark(spark, cfg, "orders") == first

    # Upsert, not append: advancing the mark keeps one row per source.
    second = datetime(2026, 7, 2, 12, 0, 0)
    set_watermark(spark, cfg, "orders", second)
    assert get_watermark(spark, cfg, "orders") == second
    assert spark.table(cfg.table("ops", "watermarks")).count() == 1


def test_log_run_appends_metrics(spark, cfg):
    ensure_ops_tables(spark, cfg)
    run_id = log_run(
        spark,
        cfg,
        task="unit_test",
        status="succeeded",
        started_at=datetime.now(UTC),
        metrics={"rows": 42},
    )
    rows = spark.table(cfg.table("ops", "pipeline_runs")).where(f"run_id = '{run_id}'").collect()
    assert len(rows) == 1
    assert rows[0]["status"] == "succeeded"
    assert rows[0]["metrics"]["rows"] == "42"
