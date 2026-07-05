"""Dump E7 results from ``ops.benchmarks`` as JSON, through the smoke cluster.

Same access path as run_p2_e2e.py: the classic cluster reaches the private
storage over private endpoints, so nothing needs to be opened up. Output goes
to stdout (and optionally a file) for docs/performance-findings.md.

Usage:
    python scripts/dump_benchmarks.py --host https://adb-....azuredatabricks.net \
        --cluster-id <id> [--catalog lakeforge_dev] [--out benchmarks.json]
"""

from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import compute


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--cluster-id", required=True)
    parser.add_argument("--catalog", default="lakeforge_dev")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    w = WorkspaceClient(host=args.host)
    if w.clusters.get(args.cluster_id).state != compute.State.RUNNING:
        print(f"cluster {args.cluster_id} not running; starting (~5 min)...")
        w.clusters.ensure_cluster_is_running(args.cluster_id)
    ctx = w.command_execution.create_and_wait(
        cluster_id=args.cluster_id, language=compute.Language.PYTHON
    )
    code = textwrap.dedent(
        f"""
        import json
        rows = spark.sql('''
            SELECT ts, category, name, config, metrics, duration_ms
            FROM {args.catalog}.ops.benchmarks
            ORDER BY category, name, ts
        ''').collect()
        out = [
            {{"ts": str(r["ts"]), "category": r["category"], "name": r["name"],
              "config": dict(r["config"] or {{}}), "metrics": dict(r["metrics"] or {{}}),
              "duration_ms": r["duration_ms"]}}
            for r in rows
        ]
        print("BENCH_JSON_START")
        print(json.dumps(out))
        print("BENCH_JSON_END")
        """
    )
    cmd = w.command_execution.execute_and_wait(
        cluster_id=args.cluster_id, context_id=ctx.id,
        language=compute.Language.PYTHON, command=code,
    )
    if cmd.results is None or str(cmd.results.result_type) in ("ResultType.ERROR", "error"):
        raise SystemExit(f"cluster command failed:\n{cmd.results and cmd.results.cause}")
    data = str(cmd.results.data or "")
    payload = data.split("BENCH_JSON_START")[1].split("BENCH_JSON_END")[0].strip()
    records = json.loads(payload)
    print(f"{len(records)} benchmark rows")
    if args.out:
        Path(args.out).write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
