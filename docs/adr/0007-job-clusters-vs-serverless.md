# ADR-0007: Classic job clusters (spot, single-node) instead of serverless jobs

**Status:** accepted (P3, revalidated P4) · **Related:** FR-5.4, NFR-2, FR-9.3

## Context

Every scheduled workload needs compute. Options: serverless jobs compute,
classic job clusters, or an always-on all-purpose cluster shared by jobs.

## Decision

**Classic job clusters defined in the bundle** — pinned LTS runtime,
single-node by default, Azure spot with on-demand fallback. No all-purpose
cluster is ever used by jobs; serverless jobs stay off.

## Rationale & trade-offs

- **Network:** the lakehouse storage sits behind private endpoints with public
  access disabled (FR-1.8). Classic clusters live in the customer VNet and
  reach it through those endpoints. Serverless compute runs in Databricks'
  account and needs Network Connectivity Config private endpoints first — and
  NCC administration requires the account console, which is currently blocked
  for this tenant setup (see `docs/identity-matrix.md`). Serverless would be
  broken-by-default here.
- **Cost control:** spot D4s_v3 runs at ~19% of the on-demand VM price
  (measured in `docs/performance-findings.md`); single-node covers the 15K-row
  medallion workload with headroom. Serverless removes the VM line item but
  prices the convenience into the DBU rate and removes the spot lever.
- **Determinism:** pinned `spark_version` in the bundle means the runtime only
  changes when a PR says so; serverless upgrades on Databricks' schedule.
- Trade-off: ~3–4 min cluster start latency per run (fine for a daily batch)
  and quota management stays ours — the 10 vCPU regional cap actively shapes
  the perf-lab design (sequential probes; see ADR-0008).
