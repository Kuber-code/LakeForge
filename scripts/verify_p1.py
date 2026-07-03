"""P1 exit-criteria verification (docs/requirements.md §6).

Checks, in order:
  1. POSITIVE  — a cluster reads a file from ADLS through the Access Connector
                 (upload to the landing volume, spark.read it on the smoke cluster)
  2. GRANTS    — engineer (you) can create tables in silver & gold
  3. NEGATIVE  — the analyst SP is DENIED on silver, but can SELECT on gold

Auth: you = Azure CLI; analyst SP = client id/secret pulled from Key Vault
(never passed on the command line).

Usage:
    python verify_p1.py --host https://adb-....azuredatabricks.net \
        --cluster-id <id> --warehouse-id <id> --key-vault <kv-name>

Requires: databricks-sdk, Azure CLI logged in.
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import compute, sql

CATALOG = "lakeforge_dev"
VOLUME_PATH = f"/Volumes/{CATALOG}/bronze/landing/smoke/verify_p1.csv"

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))


def kv_secret(vault: str, name: str) -> str:
    out = subprocess.run(
        ["az", "keyvault", "secret", "show", "--vault-name", vault, "--name", name, "-o", "json"],
        capture_output=True, text=True, check=True, shell=sys.platform == "win32",
    )
    return json.loads(out.stdout)["value"]


def az_tenant() -> str:
    out = subprocess.run(
        ["az", "account", "show", "-o", "json"],
        capture_output=True, text=True, check=True, shell=sys.platform == "win32",
    )
    return json.loads(out.stdout)["tenantId"]


def ensure_cluster_running(w: WorkspaceClient, cluster_id: str) -> None:
    state = w.clusters.get(cluster_id).state
    if state not in (compute.State.RUNNING,):
        print(f"cluster {cluster_id} is {state}; starting (can take ~5 min)...")
        w.clusters.ensure_cluster_is_running(cluster_id)


def check_cluster_reads_adls(w: WorkspaceClient, cluster_id: str) -> None:
    w.files.upload(VOLUME_PATH, io.BytesIO(b"id,msg\n1,lakeforge-p1\n"), overwrite=True)

    ensure_cluster_running(w, cluster_id)
    ctx = w.command_execution.create_and_wait(cluster_id=cluster_id, language=compute.Language.PYTHON)
    try:
        cmd = w.command_execution.execute_and_wait(
            cluster_id=cluster_id,
            context_id=ctx.id,
            language=compute.Language.PYTHON,
            command=(
                f"df = spark.read.option('header', True).csv('{VOLUME_PATH}')\n"
                "print('ROWS=' + str(df.count()) + ' MSG=' + df.first().msg)"
            ),
        )
        out = (cmd.results and cmd.results.data) or ""
        ok = cmd.status == compute.CommandStatus.FINISHED and "ROWS=1" in str(out) and "lakeforge-p1" in str(out)
        record("cluster reads ADLS via Access Connector (UC volume)", ok, str(out).strip()[:120])
    finally:
        w.command_execution.destroy(cluster_id=cluster_id, context_id=ctx.id)


def run_sql(w: WorkspaceClient, warehouse_id: str, statement: str) -> sql.StatementResponse:
    resp = w.statement_execution.execute_statement(
        statement=statement, warehouse_id=warehouse_id, catalog=CATALOG, wait_timeout="50s"
    )
    # serverless warm-up may exceed wait_timeout
    while resp.status and resp.status.state in (sql.StatementState.PENDING, sql.StatementState.RUNNING):
        time.sleep(3)
        resp = w.statement_execution.get_statement(resp.statement_id)
    return resp


def check_grants(w_me: WorkspaceClient, host: str, warehouse_id: str, key_vault: str) -> None:
    for stmt in (
        "CREATE TABLE IF NOT EXISTS silver.p1_smoke_silver AS SELECT 1 AS id, 'secret-ish' AS payload",
        "CREATE TABLE IF NOT EXISTS gold.p1_smoke_gold  AS SELECT 1 AS id, 'public-ish' AS payload",
    ):
        resp = run_sql(w_me, warehouse_id, stmt)
        if resp.status.state != sql.StatementState.SUCCEEDED:
            record(f"engineer DDL: {stmt[:40]}...", False, str(resp.status.error))
            return
    record("engineer can create tables in silver & gold", True)

    analyst = WorkspaceClient(
        host=host,
        azure_client_id=kv_secret(key_vault, "sp-analyst-client-id"),
        azure_client_secret=kv_secret(key_vault, "sp-analyst-client-secret"),
        azure_tenant_id=az_tenant(),
    )

    resp = run_sql(analyst, warehouse_id, "SELECT * FROM gold.p1_smoke_gold")
    record(
        "analyst SP can SELECT on gold",
        resp.status.state == sql.StatementState.SUCCEEDED,
        str(resp.status.state),
    )

    resp = run_sql(analyst, warehouse_id, "SELECT * FROM silver.p1_smoke_silver")
    denied = resp.status.state == sql.StatementState.FAILED and (
        "PERMISSION" in str(resp.status.error).upper() or "DENIED" in str(resp.status.error).upper()
        or "INSUFFICIENT" in str(resp.status.error).upper()
    )
    record("analyst SP DENIED on silver (negative test)", denied,
           str(resp.status.error and resp.status.error.message)[:120])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", required=True)
    p.add_argument("--cluster-id", required=True)
    p.add_argument("--warehouse-id", required=True)
    p.add_argument("--key-vault", required=True)
    args = p.parse_args()

    me = WorkspaceClient(host=args.host)  # Azure CLI auth
    print(f"authenticated as: {me.current_user.me().user_name}")

    check_cluster_reads_adls(me, args.cluster_id)
    check_grants(me, args.host, args.warehouse_id, args.key_vault)

    print("\n" + "=" * 60)
    failed = [r for r in RESULTS if not r[1]]
    print(f"P1 exit criteria: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
