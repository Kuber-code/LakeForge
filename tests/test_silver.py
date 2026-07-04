from datetime import date, datetime
from decimal import Decimal

from pyspark.sql import functions as F

from lakeforge.transform.silver import (
    CUSTOMER_TRACKED_COLS,
    apply_casts,
    latest_per_key,
    referential_violations,
    scd2_upsert,
    upsert,
)

T0 = datetime(2026, 7, 1, 8, 0, 0)
T1 = datetime(2026, 7, 2, 8, 0, 0)
T2 = datetime(2026, 7, 3, 8, 0, 0)

CUSTOMER_SCHEMA = (
    "customer_id INT, customer_name STRING, city STRING, region STRING, "
    "segment STRING, credit_limit DECIMAL(12,2), modified_at TIMESTAMP"
)


def _customers(spark, rows):
    return spark.createDataFrame(rows, CUSTOMER_SCHEMA)


def test_latest_per_key_keeps_newest_version(spark):
    df = spark.createDataFrame(
        [(1, "old", T0), (1, "new", T1), (2, "only", T0)],
        "id INT, v STRING, modified_at TIMESTAMP",
    )
    got = {r["id"]: r["v"] for r in latest_per_key(df, "id").collect()}
    assert got == {1: "new", 2: "only"}


def test_apply_casts_types_and_keeps_metadata(spark):
    df = spark.createDataFrame(
        [("7", "2026-07-01", "f.csv")], "shipment_id STRING, ship_date STRING, _source_file STRING"
    )
    out = apply_casts(df, {"shipment_id": "int", "ship_date": "date"})
    assert dict(out.dtypes) == {
        "shipment_id": "int",
        "ship_date": "date",
        "_source_file": "string",
    }


def test_referential_violations_finds_orphans(spark):
    orders = spark.createDataFrame([(1, 10), (2, 99)], "order_id INT, customer_id INT")
    customers = spark.createDataFrame([(10,)], "customer_id INT")
    orphans = referential_violations(orders, customers, "customer_id").collect()
    assert [r["order_id"] for r in orphans] == [2]


class TestScd2:
    """P2 exit criterion in miniature: a changed customer produces a closed
    old version and a new current one."""

    def _target(self, cfg):
        return cfg.table("silver", "customers")

    def test_initial_load_all_current(self, spark, cfg):
        updates = _customers(
            spark, [(1, "Browar A", "Poznan", "west", "Retail", Decimal("1000.00"), T0)]
        )
        scd2_upsert(spark, self._target(cfg), updates, "customer_id", CUSTOMER_TRACKED_COLS)

        rows = spark.table(self._target(cfg)).collect()
        assert len(rows) == 1
        assert rows[0]["is_current"] is True
        assert rows[0]["valid_to"] is None
        assert rows[0]["valid_from"] == T0

    def test_changed_record_closes_old_version(self, spark, cfg):
        scd2_upsert(
            spark,
            self._target(cfg),
            _customers(
                spark, [(1, "Browar A", "Poznan", "west", "Retail", Decimal("1000.00"), T0)]
            ),
            "customer_id",
            CUSTOMER_TRACKED_COLS,
        )
        # The customer moves city -> new SCD2 version.
        scd2_upsert(
            spark,
            self._target(cfg),
            _customers(
                spark, [(1, "Browar A", "Warszawa", "central", "Retail", Decimal("1000.00"), T1)]
            ),
            "customer_id",
            CUSTOMER_TRACKED_COLS,
        )

        rows = spark.table(self._target(cfg)).orderBy("valid_from").collect()
        assert len(rows) == 2
        old, new = rows
        assert old["is_current"] is False
        assert old["valid_to"] == T1
        assert old["city"] == "Poznan"
        assert new["is_current"] is True
        assert new["valid_to"] is None
        assert new["city"] == "Warszawa"
        assert new["valid_from"] == T1

    def test_unchanged_record_is_noop(self, spark, cfg):
        batch = _customers(
            spark, [(1, "Browar A", "Poznan", "west", "Retail", Decimal("1000.00"), T0)]
        )
        scd2_upsert(spark, self._target(cfg), batch, "customer_id", CUSTOMER_TRACKED_COLS)
        # Same values, newer modified_at: no new version (FR-4.6).
        rerun = _customers(
            spark, [(1, "Browar A", "Poznan", "west", "Retail", Decimal("1000.00"), T1)]
        )
        scd2_upsert(spark, self._target(cfg), rerun, "customer_id", CUSTOMER_TRACKED_COLS)
        assert spark.table(self._target(cfg)).count() == 1

    def test_rerun_same_batch_is_idempotent(self, spark, cfg):
        batch = _customers(
            spark,
            [
                (1, "Browar A", "Poznan", "west", "Retail", Decimal("1000.00"), T0),
                (2, "Hurt B", "Gdansk", "north", "Wholesale", Decimal("5000.00"), T0),
            ],
        )
        for _ in range(2):
            scd2_upsert(spark, self._target(cfg), batch, "customer_id", CUSTOMER_TRACKED_COLS)
        df = spark.table(self._target(cfg))
        assert df.count() == 2
        assert df.where("is_current = true").count() == 2

    def test_new_key_inserted_alongside_change(self, spark, cfg):
        scd2_upsert(
            spark,
            self._target(cfg),
            _customers(
                spark, [(1, "Browar A", "Poznan", "west", "Retail", Decimal("1000.00"), T0)]
            ),
            "customer_id",
            CUSTOMER_TRACKED_COLS,
        )
        mixed = _customers(
            spark,
            [
                (
                    1,
                    "Browar A",
                    "Poznan",
                    "west",
                    "HoReCa",
                    Decimal("1000.00"),
                    T2,
                ),  # segment change
                (3, "Nowy C", "Lodz", "central", "Retail", Decimal("700.00"), T2),  # brand-new key
            ],
        )
        scd2_upsert(spark, self._target(cfg), mixed, "customer_id", CUSTOMER_TRACKED_COLS)

        df = spark.table(self._target(cfg))
        assert df.count() == 3
        current = {r["customer_id"]: r for r in df.where("is_current = true").collect()}
        assert set(current) == {1, 3}
        assert current[1]["segment"] == "HoReCa"


def test_upsert_is_idempotent_and_updates(spark, cfg):
    target = cfg.table("silver", "orders_plain")
    v1 = spark.createDataFrame(
        [(1, "placed", T0)], "order_id INT, status STRING, modified_at TIMESTAMP"
    )
    upsert(spark, target, v1, "order_id")
    upsert(spark, target, v1, "order_id")  # re-run: no duplicates (FR-4.6)
    assert spark.table(target).count() == 1

    v2 = spark.createDataFrame(
        [(1, "delivered", T1), (2, "placed", T1)],
        "order_id INT, status STRING, modified_at TIMESTAMP",
    )
    upsert(spark, target, v2, "order_id")
    got = {r["order_id"]: r["status"] for r in spark.table(target).collect()}
    assert got == {1: "delivered", 2: "placed"}


def test_cdf_captures_order_status_change(spark, cfg):
    """FR-4.3: silver.orders has CDF on; a MERGE update shows up in the feed."""
    target = cfg.table("silver", "orders_cdf")
    spark.sql(
        f"CREATE TABLE {target} (order_id INT, status STRING, modified_at TIMESTAMP) "
        "TBLPROPERTIES (delta.enableChangeDataFeed = true)"
    )
    upsert(
        spark,
        target,
        spark.createDataFrame(
            [(1, "placed", T0)], "order_id INT, status STRING, modified_at TIMESTAMP"
        ),
        "order_id",
    )
    upsert(
        spark,
        target,
        spark.createDataFrame(
            [(1, "delivered", T1)], "order_id INT, status STRING, modified_at TIMESTAMP"
        ),
        "order_id",
    )

    changes = (
        spark.read.format("delta")
        .option("readChangeFeed", "true")
        .option("startingVersion", 0)
        .table(target)
    )
    change_types = {r["_change_type"] for r in changes.collect()}
    assert {"insert", "update_preimage", "update_postimage"} <= change_types


def test_run_silver_end_to_end(spark, cfg):
    """Fabricated bronze -> run_silver: SCD2 + upserts + file casts + ref check."""
    from lakeforge.transform.silver import run_silver

    def bronze(name, rows, schema):
        spark.createDataFrame(rows, schema).withColumn(
            "_ingest_ts", F.current_timestamp()
        ).write.saveAsTable(cfg.table("bronze", name))

    bronze(
        "customers",
        [(1, "Browar A", "Poznan", "west", "Retail", Decimal("1000.00"), T0, T0)],
        CUSTOMER_SCHEMA.replace(
            "modified_at TIMESTAMP", "created_at TIMESTAMP, modified_at TIMESTAMP"
        ),
    )
    bronze(
        "products",
        [(1, "SKU-1", "Pils 0.5", "Forge", "lager", Decimal("4.50"), "bottle 0.5", T0)],
        "product_id INT, sku STRING, product_name STRING, brand STRING, category STRING, "
        "unit_price DECIMAL(9,2), package STRING, modified_at TIMESTAMP",
    )
    bronze(
        "orders",
        [(1, 1, date(2026, 7, 1), "placed", "direct", T0, T0)],
        "order_id INT, customer_id INT, order_date DATE, status STRING, channel STRING, "
        "created_at TIMESTAMP, modified_at TIMESTAMP",
    )
    bronze(
        "order_lines",
        [(1, 1, 1, 10, Decimal("4.50"), Decimal("0.00"), T0)],
        "order_line_id INT, order_id INT, product_id INT, quantity INT, "
        "unit_price DECIMAL(9,2), discount_pct DECIMAL(5,2), modified_at TIMESTAMP",
    )
    bronze(
        "deliveries",
        [(1, 1, date(2026, 7, 3), date(2026, 7, 3), "DHL", "delivered", T0)],
        "delivery_id INT, order_id INT, planned_date DATE, actual_date DATE, "
        "carrier STRING, status STRING, modified_at TIMESTAMP",
    )
    bronze(
        "shipments",
        [("100", "1", "Dystrybutor X", "2026-07-02", "5", "WAW-1")],
        "shipment_id STRING, order_id STRING, distributor STRING, ship_date STRING, "
        "qty_cases STRING, warehouse STRING",
    )

    metrics = run_silver(spark, cfg)

    assert spark.table(cfg.table("silver", "customers")).count() == 1
    assert spark.table(cfg.table("silver", "orders")).count() == 1
    assert dict(spark.table(cfg.table("silver", "shipments")).dtypes)["qty_cases"] == "int"
    assert metrics["orders_ref_violations"] == "0"
    assert int(metrics["rows_changed"]) > 0

    # Re-run over identical bronze: nothing changes anywhere (FR-4.6), and
    # the FR-5.3 signal reports exactly 0 changed rows.
    rerun = run_silver(spark, cfg)
    assert rerun["rows_changed"] == "0"
    assert spark.table(cfg.table("silver", "customers")).count() == 1
    assert spark.table(cfg.table("silver", "orders")).count() == 1
