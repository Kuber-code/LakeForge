"""FR-8.4 — SQL alert: gold freshness > 24h -> e-mail notification.

Creates (or updates) a Databricks SQL alert that evaluates hourly on the
dashboards' warehouse. The alert query measures hours since the last
successful gold refresh recorded in ``ops.pipeline_runs`` and trips when it
exceeds 24.

Idempotent: an existing alert with the same display name is updated in place.

Usage:
    python scripts/create_freshness_alert.py \
        --host https://adb-....azuredatabricks.net \
        --warehouse-id 25e5ba038b3f5267 \
        [--catalog lakeforge_prod] [--email kuba.lichosik@gmail.com]

Auth: same chain as the CLI (az login / DATABRICKS_* env vars).
"""

from __future__ import annotations

import argparse

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import (
    AlertV2,
    AlertV2Evaluation,
    AlertV2Notification,
    AlertV2Operand,
    AlertV2OperandColumn,
    AlertV2OperandValue,
    AlertV2Subscription,
    ComparisonOperator,
    CronSchedule,
)

ALERT_NAME = "LakeForge — gold freshness > 24h"

QUERY = """
SELECT coalesce(
         timestampdiff(
           HOUR,
           (SELECT max(finished_at) FROM {catalog}.ops.pipeline_runs
             WHERE task = 'gold' AND status = 'succeeded'),
           current_timestamp()
         ),
         999
       ) AS hours_since_gold_refresh
""".strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--catalog", default="lakeforge_prod")
    parser.add_argument("--email", default="kuba.lichosik@gmail.com")
    parser.add_argument("--threshold-hours", type=int, default=24)
    args = parser.parse_args()

    w = WorkspaceClient(host=args.host)

    alert = AlertV2(
        display_name=ALERT_NAME,
        query_text=QUERY.format(catalog=args.catalog),
        warehouse_id=args.warehouse_id,
        evaluation=AlertV2Evaluation(
            source=AlertV2OperandColumn(name="hours_since_gold_refresh"),
            comparison_operator=ComparisonOperator.GREATER_THAN,
            threshold=AlertV2Operand(
                value=AlertV2OperandValue(double_value=float(args.threshold_hours))
            ),
            notification=AlertV2Notification(
                subscriptions=[AlertV2Subscription(user_email=args.email)],
                retrigger_seconds=6 * 3600,  # re-notify at most every 6h while stale
            ),
        ),
        # hourly, on the hour
        schedule=CronSchedule(quartz_cron_schedule="0 0 * * * ?", timezone_id="UTC"),
    )

    existing = [
        a for a in w.alerts_v2.list_alerts() if a.display_name == ALERT_NAME
    ]
    if existing:
        result = w.alerts_v2.update_alert(
            id=existing[0].id, alert=alert, update_mask="*"
        )
        print(f"updated alert {result.id}: {ALERT_NAME}")
    else:
        result = w.alerts_v2.create_alert(alert=alert)
        print(f"created alert {result.id}: {ALERT_NAME}")
    print(f"query targets {args.catalog}; threshold {args.threshold_hours}h; -> {args.email}")


if __name__ == "__main__":
    main()
