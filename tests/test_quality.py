from datetime import datetime

import pytest

from lakeforge.ops import ensure_ops_tables
from lakeforge.quality.gates import (
    QualityGateError,
    null_ratio_max,
    pk_unique,
    row_count_min,
    run_gates,
)

T0 = datetime(2026, 7, 1)


@pytest.fixture()
def df(spark):
    return spark.createDataFrame([(1, "a"), (2, None), (2, "c")], "id INT, v STRING")


def test_row_count_min(df):
    assert row_count_min(df, "t", 3).passed
    assert not row_count_min(df, "t", 4).passed


def test_pk_unique(df):
    result = pk_unique(df, "t", "id")
    assert not result.passed
    assert result.observed == "1 duplicate keys"
    assert pk_unique(df.dropDuplicates(["id"]), "t", "id").passed


def test_null_ratio_max(df):
    assert null_ratio_max(df, "t", "v", 0.5).passed
    assert not null_ratio_max(df, "t", "v", 0.1).passed


def test_run_gates_logs_and_raises(spark, cfg, df):
    ensure_ops_tables(spark, cfg)
    results = [row_count_min(df, "t", 1), pk_unique(df, "t", "id")]

    with pytest.raises(QualityGateError, match="pk_unique"):
        run_gates(spark, cfg, results, task="unit_gates")

    logged = spark.table(cfg.table("ops", "pipeline_runs")).where("task = 'unit_gates'").collect()
    assert len(logged) == 1
    assert logged[0]["status"] == "failed"
    assert "FAIL" in logged[0]["metrics"]["pk_unique:t"]


def test_run_gates_all_pass_logs_success(spark, cfg, df):
    ensure_ops_tables(spark, cfg)
    run_gates(spark, cfg, [row_count_min(df, "t", 1)], task="unit_gates_ok")
    logged = (
        spark.table(cfg.table("ops", "pipeline_runs")).where("task = 'unit_gates_ok'").collect()
    )
    assert logged[0]["status"] == "succeeded"
