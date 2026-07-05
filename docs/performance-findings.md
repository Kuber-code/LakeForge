# Performance findings (E7)

Measured on **2026-07-05**, job `lakeforge-perf-lab-dev` (74 min wall end-to-end,
all clusters spot). Raw rows live in `lakeforge_dev.ops.benchmarks`; charts in
the *Performance & Cost* dashboard. Reproduce with
`databricks bundle run perf_lab -t dev`.

**Setup (FR-7.1):** deterministic synthetic sales fact, **50M rows / ~1.7 GB**
Delta, 3 years of dates, 50K customers with one hot key holding ~30% of rows,
unique `order_ref` as the high-cardinality clustering column
(`src/lakeforge/perf/generator.py`). Runtime: DBR 17.3 LTS.
All reported durations are the **median of warm runs** (3 executions, first
discarded); cold times noted where they change the story.

## FR-7.3 — physical layout

Same 50M rows under five layouts:

| layout | files | size | how |
|---|---|---|---|
| smallfiles | 1 600 | 1.82 GB | `repartition(1600)` write |
| compacted | 32 | 1.71 GB | `OPTIMIZE` (bin-packing) |
| zorder | 23 | 1.57 GB | `OPTIMIZE ZORDER BY (customer_id, sale_date)` |
| liquid | 22 | 1.57 GB | `CLUSTER BY (customer_id, sale_date)` |
| overpartitioned | **17 520** | 1.79 GB | `PARTITIONED BY (sale_date)` — 1 095 partitions |

Median warm duration (ms) on the shared single-node D8s_v3:

| query | smallfiles | compacted | zorder | liquid | overpartitioned |
|---|---|---|---|---|---|
| selective (customer + 30-day window) | 7 153 | 1 588 | **558** | **549** | 1 457 |
| single day | 6 350 | 1 073 | 567 | 567 | **674** |
| full-table aggregation | 7 301 | 2 230 | 2 192 | 2 260 | **23 329** |

What the numbers say:

- **Small files are a 3–13× tax on everything.** 1 600 files vs 32 for the
  same bytes: every query pays listing + open overhead. `OPTIMIZE` alone
  bought 4.5× on the selective query.
- **Clustering (Z-ORDER or liquid) buys another ~3×** on selective queries
  (1 588 → ~550 ms) by letting Delta skip files on `customer_id`/`sale_date`
  stats. On full scans it neither helps nor hurts.
- **Over-partitioning is the worst of all worlds at this size.** Daily
  partitions put ~46K rows in each of 1 095 directories (17 520 files). It
  wins nothing — even its home game, the single-day query (674 ms), loses to
  clustered layouts (567 ms) — and the full scan collapses to 23 s, **10×
  slower than compacted**. A date partition column only starts paying off
  when each partition is GBs, not MBs.
- **Z-ORDER vs liquid: identical read performance here** (549 vs 558 ms).
  The decision between them is operational, not speed — see ADR-0005 (liquid
  keys are table metadata, re-cluster incrementally, and can be changed).
- Skew note: the hot-key lookup (`customer_id = 42`, 15M rows) runs ~175 ms
  on both compacted and liquid — clustering can't isolate a key that lives in
  every file range; skew is a join problem (see AQE below), not a layout one.

## FR-7.2 — cluster experiments

Same three workloads per cluster (spot, DBR 17.3): full-scan aggregation,
skewed join + aggregation, selective read. Median warm ms:

| workload | single 4c | single 4c + Photon | 2× 4c (driver+worker) | single 8c |
|---|---|---|---|---|
| full-scan agg | 10 271 | 4 887 | 8 779 | 4 959 |
| skewed join | 13 572 | 4 914 | 13 835 | 5 113 |
| selective read | 3 379 | 2 386 | 3 713 | 1 559 |
| **suite total** | **27.2 s** | **12.2 s** | **26.3 s** | **11.6 s** |

- **Scale-up beat scale-out at equal vCPUs.** One 8-core box ran the suite
  2.3× faster than driver+worker at 4 cores each — the 2-node cluster must
  shuffle the skewed join over the network and its driver does double duty,
  while single-node keeps everything in `local[*]`. On the skewed join the
  second node bought *nothing* (13 835 vs 13 572 ms single 4c). Lesson: for
  sub-10 GB working sets, buy a bigger node before buying more nodes.
- **Photon: 2.1–2.8× on scans and joins** on identical silicon (and it
  roughly doubled the *cold* full-scan too: 41.5 s → 22.9 s). Photon's DBU
  draw is higher, so it pays when compute time dominates — reconcile exact
  DBUs in the cost dashboard once `system.billing` access is granted.
- **Spot economics (Azure retail, westeurope, July 2026):** D4s_v3 spot
  $0.0444/h vs $0.24/h on-demand (**−81.5%**); D8s_v3 $0.0887 vs $0.48. With
  spot VMs, DBUs dominate the bill: a 10-minute probe on D4s_v3 costs ~$0.007
  VM + ~$0.037 DBU (0.75 DBU/h × premium jobs rate) — ~84% of the cost is
  DBUs. `SPOT_WITH_FALLBACK_AZURE` + `first_on_demand: 1` protects the driver
  from eviction; no eviction was observed across the lab.
- **Autoscaling under skew: not runnable within quota.** The 10 vCPU regional
  cap can't fit driver + 2 workers (12 vCPU), so the scale-up trigger can't
  be observed. Documented as a quota constraint; rerun with autoscale 1→3
  after a quota bump. The same cap forced the lab's probes to run strictly
  sequentially (task retries absorb the VM-deallocation overlap window — both
  observed INTERNAL_ERROR-then-retry-success events were exactly that).

## FR-7.4 — query optimization, before → after

| case | bad (ms) | rewritten (ms) | gain | fix |
|---|---|---|---|---|
| exploding join + DISTINCT | 3 753 | 2 062 | 1.8× | date-overlap predicate moved *into* the join condition; DISTINCT dropped (row counts verified identical: 1 962 258) |
| non-sargable filter | 1 162 | 803 | 1.4× | `year(d)=2024 AND month(d)=6` → `BETWEEN '2024-06-01' AND '2024-06-30'` — file skipping works again on the clustered column |
| needless DISTINCT on unique key | 5 339 | 1 290 | **4.1×** | `sale_id` is already unique; DISTINCT forced a full-width shuffle + dedup of 8.3M rows for nothing |
| shuffle join vs broadcast (200-row dim) | 3 219 | 2 717 | 1.2× warm, **2.5× cold** (7 687 → 3 131) | let the optimizer broadcast the dimension instead of `autoBroadcastJoinThreshold=-1` |
| skewed join, AQE off → on | 17 680 | 6 137 | **2.9×** | AQE skew-join handling splits the hot key's 15M-row partition; with AQE off one task drags the whole stage |

`EXPLAIN FORMATTED` plans for each pair are printed in the `query_lab` task
log of the perf-lab run (job `lakeforge-perf-lab-dev`, task `query_lab`).
The two headline plan diffs: DISTINCT shows up as an extra
`HashAggregate`/`Exchange` pair over the full output width, and the broadcast
rewrite replaces `SortMergeJoin` + two `Exchange`s with `BroadcastHashJoin`.

## FR-7.5 — Delta maintenance

On a dedicated 1M-row table (create → `UPDATE` → `DELETE` → `OPTIMIZE`):

- **`DESCRIBE HISTORY` forensics:** every operation appears with
  `operationMetrics` (rows updated/deleted, files added/removed) — the audit
  trail answered "who removed 14 rows" without any extra tooling.
- **Time travel:** `VERSION AS OF 0` read the pre-delete state (1 000 000
  rows vs 999 986 current) in 891 ms; `RESTORE TABLE ... TO VERSION AS OF 1`
  rolled the table back in place.
- **VACUUM retention trade-off:** at the default 7-day retention a fresh
  table has **0** eligible files — that is the safety margin working. With the
  guard off, `VACUUM RETAIN 0 HOURS` removed the 5 stale files (17.4 s).
  Nuance worth knowing: time travel to v0 *still worked* afterwards, because
  the preceding RESTORE made v0/v1 files current again — VACUUM breaks time
  travel only to versions whose files are no longer referenced by the current
  snapshot. Retention is a contract between time-travel depth and storage
  cost; 7 days default, `delta.deletedFileRetentionDuration` per table where
  the trade-off differs.

## Caveats

- One day, one region, small silicon: treat ratios as directional, absolute
  milliseconds as anecdotes. Medians of 2 warm runs bound noise but won't
  survive a t-test.
- The 50M-row fact fits in one node's page cache after the first scan; disk
  and network effects would reshape results at 500M+ rows.
- DBU-exact cost per variant lands in the *Performance & Cost* dashboard from
  `system.billing.usage` (tagged `perf_variant`) once system-schema access is
  granted (account console — see ADR-0008 / identity-matrix).
