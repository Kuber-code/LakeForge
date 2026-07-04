from datetime import date, datetime
from decimal import Decimal

import pytest

from lakeforge.transform.gold import (
    build_agg_daily_revenue,
    build_agg_delivery_sla,
    build_dim_customer,
    build_dim_date,
    build_dim_product,
    build_fact_sales,
)

T0 = datetime(2026, 6, 1)
T1 = datetime(2026, 6, 20)

SCD2_SCHEMA = (
    "customer_id INT, customer_name STRING, city STRING, region STRING, segment STRING, "
    "credit_limit DECIMAL(12,2), valid_from TIMESTAMP, valid_to TIMESTAMP, is_current BOOLEAN"
)


@pytest.fixture()
def dim_customer(spark):
    # Customer 1 moved from west (until T1) to central (current).
    scd2 = spark.createDataFrame(
        [
            (1, "Browar A", "Poznan", "west", "Retail", Decimal("1000.00"), T0, T1, False),
            (1, "Browar A", "Warszawa", "central", "Retail", Decimal("1000.00"), T1, None, True),
        ],
        SCD2_SCHEMA,
    )
    return build_dim_customer(scd2)


@pytest.fixture()
def dim_product(spark):
    products = spark.createDataFrame(
        [(1, "SKU-1", "Pils 0.5", "Forge Lager", "lager", Decimal("4.00"), "bottle 0.5")],
        "product_id INT, sku STRING, product_name STRING, brand STRING, category STRING, "
        "unit_price DECIMAL(9,2), package STRING",
    )
    return build_dim_product(products)


def _orders(spark):
    return spark.createDataFrame(
        [
            (1, 1, date(2026, 6, 10), "delivered", "direct"),  # before the move
            (2, 1, date(2026, 6, 25), "placed", "direct"),  # after the move
            (3, 1, date(2026, 5, 1), "delivered", "online"),  # predates first version
            (4, 1, date(2026, 6, 26), "cancelled", "direct"),
        ],
        "order_id INT, customer_id INT, order_date DATE, status STRING, channel STRING",
    )


def _order_lines(spark):
    return spark.createDataFrame(
        [
            (10, 1, 1, 10, Decimal("4.00"), Decimal("0.00")),
            (20, 2, 1, 5, Decimal("4.00"), Decimal("10.00")),  # 5*4*0.9 = 18.00
            (30, 3, 1, 1, Decimal("4.00"), Decimal("0.00")),
            (40, 4, 1, 100, Decimal("4.00"), Decimal("0.00")),  # cancelled order
        ],
        "order_line_id INT, order_id INT, product_id INT, quantity INT, "
        "unit_price DECIMAL(9,2), discount_pct DECIMAL(5,2)",
    )


def test_dim_date_spans_min_to_max(spark):
    dim = build_dim_date(_orders(spark))
    dates = [r["date"] for r in dim.orderBy("date").collect()]
    assert dates[0] == date(2026, 5, 1)
    assert dates[-1] == date(2026, 6, 26)
    assert len(dates) == 57  # full calendar, no gaps
    keys = {r["date_key"] for r in dim.collect()}
    assert 20260510 in keys


def test_fact_sales_point_in_time_customer_version(spark, dim_customer, dim_product):
    fact = build_fact_sales(_order_lines(spark), _orders(spark), dim_customer, dim_product)
    rows = {r["order_line_id"]: r for r in fact.collect()}

    sk = {(r["customer_id"], r["is_current"]): r["customer_sk"] for r in dim_customer.collect()}
    old_sk, new_sk = sk[(1, False)], sk[(1, True)]

    assert rows[10]["customer_sk"] == old_sk  # order during the west era
    assert rows[20]["customer_sk"] == new_sk  # order after the move
    assert rows[30]["customer_sk"] == old_sk  # predates history -> earliest version
    assert rows[20]["net_amount"] == Decimal("18.00")
    assert rows[10]["date_key"] == 20260610


def test_fact_sales_no_null_surrogate_keys(spark, dim_customer, dim_product):
    fact = build_fact_sales(_order_lines(spark), _orders(spark), dim_customer, dim_product)
    assert fact.where("customer_sk IS NULL OR product_sk IS NULL").count() == 0


def test_agg_daily_revenue_excludes_cancelled(spark, dim_customer, dim_product):
    fact = build_fact_sales(_order_lines(spark), _orders(spark), dim_customer, dim_product)
    agg = build_agg_daily_revenue(fact, dim_customer, dim_product).collect()

    by_date = {(r["order_date"], r["region"]): r for r in agg}
    # Cancelled order 4 (400.00) must not appear anywhere.
    assert sum(r["net_revenue"] for r in agg) == Decimal("62.00")
    # Region comes from the point-in-time customer version.
    assert by_date[(date(2026, 6, 10), "west")]["net_revenue"] == Decimal("40.00")
    assert by_date[(date(2026, 6, 25), "central")]["net_revenue"] == Decimal("18.00")


def test_agg_delivery_sla(spark):
    deliveries = spark.createDataFrame(
        [
            (1, 1, date(2026, 6, 12), date(2026, 6, 12), "DHL", "delivered"),  # on time
            (2, 2, date(2026, 6, 12), date(2026, 6, 14), "DHL", "delivered"),  # 2 days late
            (3, 3, date(2026, 6, 12), None, "DPD", "in_transit"),  # not delivered yet
        ],
        "delivery_id INT, order_id INT, planned_date DATE, actual_date DATE, "
        "carrier STRING, status STRING",
    )
    agg = {r["carrier"]: r for r in build_agg_delivery_sla(deliveries).collect()}

    assert agg["DHL"]["deliveries"] == 2
    assert agg["DHL"]["on_time"] == 1
    assert agg["DHL"]["on_time_rate"] == 0.5
    assert agg["DHL"]["avg_delay_days"] == 1.0
    assert "DPD" not in agg  # undelivered rows don't count against SLA


def test_agg_distributor_shipments(spark):
    from lakeforge.transform.gold import build_agg_distributor_shipments

    shipments = spark.createDataFrame(
        [
            (1, 10, "BeerLine", date(2026, 6, 12), 40, "WAW-1"),
            (2, 11, "BeerLine", date(2026, 6, 12), 20, "POZ-1"),
            (3, 12, "HopTrans", date(2026, 6, 12), 10, "WAW-1"),
        ],
        "shipment_id INT, order_id INT, distributor STRING, ship_date DATE, "
        "qty_cases INT, warehouse STRING",
    )
    agg = {r["distributor"]: r for r in build_agg_distributor_shipments(shipments).collect()}
    assert agg["BeerLine"]["shipments"] == 2
    assert agg["BeerLine"]["cases_shipped"] == 60
    assert agg["BeerLine"]["warehouses_used"] == 2
    assert agg["HopTrans"]["cases_shipped"] == 10


def test_run_gold_writes_all_tables(spark, cfg, dim_customer, dim_product):
    """run_gold overwrites deterministically: same silver in, same gold out."""
    from lakeforge.transform.gold import run_gold

    spark.createDataFrame(
        [
            (1, "Browar A", "Poznan", "west", "Retail", Decimal("1000.00"), T0, None, True),
        ],
        SCD2_SCHEMA,
    ).write.saveAsTable(cfg.table("silver", "customers"))
    dim_product_src = spark.createDataFrame(
        [(1, "SKU-1", "Pils 0.5", "Forge Lager", "lager", Decimal("4.00"), "bottle 0.5")],
        "product_id INT, sku STRING, product_name STRING, brand STRING, category STRING, "
        "unit_price DECIMAL(9,2), package STRING",
    )
    dim_product_src.write.saveAsTable(cfg.table("silver", "products"))
    _orders(spark).write.saveAsTable(cfg.table("silver", "orders"))
    _order_lines(spark).write.saveAsTable(cfg.table("silver", "order_lines"))
    spark.createDataFrame(
        [(1, 1, date(2026, 6, 12), date(2026, 6, 12), "DHL", "delivered")],
        "delivery_id INT, order_id INT, planned_date DATE, actual_date DATE, "
        "carrier STRING, status STRING",
    ).write.saveAsTable(cfg.table("silver", "deliveries"))

    first = run_gold(spark, cfg)
    second = run_gold(spark, cfg)  # FR-4.6: rerun changes nothing
    assert first == second
    for table in (
        "dim_customer",
        "dim_product",
        "dim_date",
        "fact_sales",
        "agg_daily_revenue",
        "agg_delivery_sla",
    ):
        assert spark.catalog.tableExists(cfg.table("gold", table))
    assert int(first["fact_sales"]) == 4
