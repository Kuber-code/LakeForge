# ADR-0005: Liquid clustering for new large tables, Z-ORDER kept for the comparison

**Status:** accepted (P4) · **Related:** FR-7.3, FR-9.3

## Context

The perf lab (E7) materializes the same 50M-row fact under multiple layouts to
decide what LakeForge should use for large tables. Candidates for co-locating
data on the selective-query keys (`customer_id`, `sale_date`):

1. **Hive-style partitioning** on a date column.
2. **OPTIMIZE ZORDER BY** — multi-dimensional clustering at OPTIMIZE time.
3. **Liquid clustering** (`CLUSTER BY`) — declarative clustering keys,
   incremental re-clustering, keys changeable without a rewrite.

## Decision

**Liquid clustering** is the default for new large fact tables. Z-ORDER stays
in the lab as the measured baseline it replaces; per-day partitioning is
documented as an anti-pattern at this table size (see
`docs/performance-findings.md` for the measured numbers).

## Rationale & trade-offs

- Daily partitioning at ~46K rows/day produces thousands of tiny files and
  directory-listing overhead; it only wins queries filtered on exactly the
  partition key. Delta data skipping on clustered files covers that case
  without freezing the physical design.
- Z-ORDER must rewrite complete files on every OPTIMIZE run and re-clusters
  the whole table; keys are an operational convention (whoever runs OPTIMIZE
  must know them), not table metadata.
- Liquid clustering makes the keys part of the table definition, clusters new
  data incrementally, and allows changing keys later (`ALTER TABLE ... CLUSTER
  BY`) as query patterns drift — the medallion tables are expected to evolve.
- Trade-off: liquid clustering requires DBR 13.3+ writers everywhere (fine
  here — jobs pin an LTS runtime) and OSS-engine compatibility is narrower
  than plain partitioning. Acceptable for a single-platform lakehouse.
