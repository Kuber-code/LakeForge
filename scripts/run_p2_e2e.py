"""P2 exit-criteria run: the full Medallion pipeline end-to-end on Databricks.

Everything flows through the smoke cluster via the command-execution API —
the wheel and the landing files are pushed *through the cluster*, which
reaches ADLS over private endpoints and Azure SQL via its NAT egress IP, so
storage and Key Vault stay locked down (no network flip required).

Steps:
  1. install the locally built wheel on the cluster
  2. drop generated distributor files into the landing volume (FR-4.1 input)
  3. bronze: Auto Loader (files) + incremental JDBC (Azure SQL, watermark)
  4. silver -> gold -> quality gates
  5. SCD2 proof (P2 exit criterion): UPDATE one customer in Azure SQL from
     the cluster over JDBC, re-run ingest + silver, assert the old version is
     closed and a new current version exists
  6. assert gold is populated from BOTH sources (fact_sales from SQL,
     agg_distributor_shipments from files)

Usage:
    python -m pip wheel . -w dist --no-deps
    python scripts/run_p2_e2e.py --host https://adb-....azuredatabricks.net \
        --cluster-id <id> [--env dev] [--storage-account <sa>]

Requires: databricks-sdk, Azure CLI logged in. Auth: azure-cli (the human
engineer), same model as verify_p1.py.
"""

from __future__ import annotations

import argparse
import base64
import glob
import sys
import textwrap
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import compute

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "seed"))

from generate_distributor_files import generate_returns, generate_shipments  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []
SCD2_CUSTOMER_ID = 1
SCD2_NEW_CITY = "Katowice-E2E"


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))


def block(*parts: str) -> str:
    """Join code fragments, dedenting each one (mixed-indent-safe)."""
    return "\n".join(textwrap.dedent(p) for p in parts)


class ClusterSession:
    """One command-execution context on the smoke cluster."""

    def __init__(self, w: WorkspaceClient, cluster_id: str):
        self.w = w
        self.cluster_id = cluster_id
        state = w.clusters.get(cluster_id).state
        if state != compute.State.RUNNING:
            print(f"cluster {cluster_id} is {state}; starting (can take ~5 min)...")
            w.clusters.ensure_cluster_is_running(cluster_id)
        self.ctx = w.command_execution.create_and_wait(
            cluster_id=cluster_id, language=compute.Language.PYTHON
        )

    def run(self, code: str, quiet: bool = False) -> str:
        cmd = self.w.command_execution.execute_and_wait(
            cluster_id=self.cluster_id,
            context_id=self.ctx.id,
            language=compute.Language.PYTHON,
            command=code,
        )
        results = cmd.results
        if results is None or results.result_type is None:
            raise RuntimeError("no results from command execution")
        if str(results.result_type) in ("ResultType.ERROR", "error"):
            raise RuntimeError(f"cluster command failed:\n{results.cause or results.summary}")
        out = results.data or ""
        if out and not quiet:
            print(out if len(out) < 2000 else out[:2000] + " ...[truncated]")
        return str(out)

    def push_text(self, target: str, text: str) -> None:
        """Write a text file anywhere the cluster can (Volumes, /tmp)."""
        b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        self.run(
            block(
                f"""
                import base64
                _txt = base64.b64decode("{b64}").decode("utf-8")
                dbutils.fs.put("{target}", _txt, True)
                print("wrote {target} (" + str(len(_txt)) + " chars)")
                """
            ),
            quiet=True,
        )

    def push_binary_local(self, target: str, data: bytes) -> None:
        """Write a binary file onto the driver's local disk (e.g. /tmp)."""
        b64 = base64.b64encode(data).decode("ascii")
        self.run(
            block(
                f"""
                import base64
                with open("{target}", "wb") as fh:
                    fh.write(base64.b64decode("{b64}"))
                print("wrote {target}")
                """
            ),
            quiet=True,
        )


def find_wheel() -> Path:
    wheels = sorted(glob.glob(str(REPO / "dist" / "lakeforge-*.whl")))
    if not wheels:
        sys.exit("no wheel in dist/ — run: python -m pip wheel . -w dist --no-deps")
    return Path(wheels[-1])


def install_wheel(cs: ClusterSession) -> None:
    wheel = find_wheel()
    remote = f"/tmp/{wheel.name}"
    cs.push_binary_local(remote, wheel.read_bytes())
    cs.run(
        block(
            f"""
            import subprocess, sys
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--quiet",
                 "--force-reinstall", "{remote}"]
            )
            import lakeforge
            print("installed lakeforge", lakeforge.__version__)
            """
        )
    )
    record("wheel installed on cluster", True, wheel.name)


def upload_landing_files(cs: ClusterSession, cfg_code: str, run_date: str, batch: int) -> None:
    import csv as _csv
    import io
    import json as _json
    from datetime import date

    day = date.fromisoformat(run_date)
    shipments = generate_shipments(day, batch, 60)
    returns = generate_returns(day, batch, 15)

    buf = io.StringIO()
    writer = _csv.DictWriter(buf, fieldnames=list(shipments[0].keys()))
    writer.writeheader()
    writer.writerows(shipments)
    jsonl = "\n".join(_json.dumps(r) for r in returns) + "\n"

    root = cs.run(block(cfg_code, "print(cfg.landing_root)"), quiet=True).strip()
    cs.push_text(f"{root}/shipments/shipments_{run_date}_{batch}.csv", buf.getvalue())
    cs.push_text(f"{root}/returns/returns_{run_date}_{batch}.json", jsonl)
    record("landing files uploaded", True, f"{len(shipments)} shipments, {len(returns)} returns")


JDBC_SETUP = """
from lakeforge.ingest.sql import JdbcSource
jdbc = JdbcSource(
    url=dbutils.secrets.get(cfg.secret_scope, "sql-jdbc-url"),
    user=dbutils.secrets.get(cfg.secret_scope, "sql-admin-login"),
    password=dbutils.secrets.get(cfg.secret_scope, "sql-admin-password"),
)
"""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", required=True)
    p.add_argument("--cluster-id", required=True)
    p.add_argument("--env", default="dev")
    p.add_argument("--storage-account", default="stlakeforgedevsh93zt")
    p.add_argument("--date", default=None, help="landing-file business date (default: today)")
    args = p.parse_args()

    from datetime import date

    run_date = args.date or date.today().isoformat()

    w = WorkspaceClient(host=args.host, auth_type="azure-cli")
    print(f"authenticated as: {w.current_user.me().user_name}")
    cs = ClusterSession(w, args.cluster_id)

    cfg_code = f"""
    from lakeforge.config import for_env
    cfg = for_env("{args.env}", "{args.storage_account}")
    """

    install_wheel(cs)
    upload_landing_files(cs, cfg_code, run_date, batch=1)

    # --- bronze: files (FR-4.1) + SQL (FR-4.2) ---
    cs.run(
        block(
            cfg_code,
            """
            from lakeforge.ops import ensure_ops_tables
            ensure_ops_tables(spark, cfg)
            from lakeforge.ingest.files import run_bronze_files
            for source in ("shipments", "returns"):
                print(source, "rows:", run_bronze_files(spark, cfg, source))
            """,
        )
    )
    record("bronze files (Auto Loader)", True)

    cs.run(
        block(
            cfg_code,
            JDBC_SETUP,
            """
            from lakeforge.config import SQL_SOURCES
            from lakeforge.ingest.sql import run_bronze_sql
            for table in SQL_SOURCES:
                print(run_bronze_sql(spark, cfg, jdbc, table))
            """,
        )
    )
    record("bronze SQL (incremental JDBC)", True)

    # --- silver + gold + gates (FR-4.3/4.4/4.5) ---
    cs.run(
        block(
            cfg_code,
            """
            from lakeforge.transform.silver import run_silver
            print(run_silver(spark, cfg))
            """,
        )
    )
    record("silver", True)

    cs.run(
        block(
            cfg_code,
            """
            from lakeforge.transform.gold import run_gold
            print(run_gold(spark, cfg))
            """,
        )
    )
    record("gold", True)

    cs.run(
        block(
            cfg_code,
            """
            from lakeforge.quality.gates import run_gates, standard_gates
            run_gates(spark, cfg, standard_gates(spark, cfg))
            print("all quality gates passed")
            """,
        )
    )
    record("quality gates", True)

    # --- exit criterion: gold populated from both sources ---
    out = cs.run(
        block(
            cfg_code,
            """
            fact = spark.table(cfg.table("gold", "fact_sales")).count()
            dist = spark.table(cfg.table("gold", "agg_distributor_shipments")).count()
            print(f"CHECK fact_sales={fact} agg_distributor_shipments={dist}")
            """,
        )
    )
    ok = "CHECK" in out and "fact_sales=0" not in out and "agg_distributor_shipments=0" not in out
    record("gold populated from both sources", ok, out.strip().splitlines()[-1])

    # --- exit criterion: SCD2 with a changed customer record ---
    before = cs.run(
        block(
            cfg_code,
            f"""
            t = spark.table(cfg.table("silver", "customers"))
            print(t.where("customer_id = {SCD2_CUSTOMER_ID}").count())
            """,
        ),
        quiet=True,
    ).strip()

    cs.run(
        block(
            cfg_code,
            JDBC_SETUP,
            f"""
            # 3-arg overload: credentials never touch the URL, no escaping issues.
            conn = spark._sc._jvm.java.sql.DriverManager.getConnection(
                jdbc.url, jdbc.user, jdbc.password
            )
            try:
                stmt = conn.createStatement()
                n = stmt.executeUpdate(
                    "UPDATE dbo.customers SET city = '{SCD2_NEW_CITY}', "
                    "modified_at = SYSUTCDATETIME() WHERE customer_id = {SCD2_CUSTOMER_ID}"
                )
                print("updated rows:", n)
            finally:
                conn.close()
            """,
        )
    )
    cs.run(
        block(
            cfg_code,
            JDBC_SETUP,
            """
            from lakeforge.ingest.sql import run_bronze_sql
            from lakeforge.transform.silver import run_silver
            print(run_bronze_sql(spark, cfg, jdbc, "customers"))
            print(run_silver(spark, cfg))
            """,
        )
    )
    out = cs.run(
        block(
            cfg_code,
            f"""
            t = spark.table(cfg.table("silver", "customers")).where(
                "customer_id = {SCD2_CUSTOMER_ID}"
            )
            total = t.count()
            current = t.where("is_current = true")
            closed = t.where("is_current = false AND valid_to IS NOT NULL").count()
            row = current.collect()[0]
            print(
                "SCD2 total=" + str(total)
                + " current_city=" + row["city"]
                + " current_rows=" + str(current.count())
                + " closed_rows=" + str(closed)
            )
            """,
        )
    )
    line = out.strip().splitlines()[-1]
    ok = (
        f"current_city={SCD2_NEW_CITY}" in line
        and "current_rows=1" in line
        and f"total={int(before) + 1}" in line
    )
    record("SCD2: changed customer -> closed old + new current version", ok, line)

    print("\n" + "=" * 60)
    failed = [r for r in RESULTS if not r[1]]
    for name, ok, _ in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
