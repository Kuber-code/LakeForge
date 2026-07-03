# ADR-0004: Managed tables everywhere, per-layer managed locations

**Status:** accepted (P1) · **Related:** FR-3.2

## Context

FR-3.2 requires managed tables in silver/gold and a justified choice for
bronze. External tables give path-addressable files; managed tables give UC
lifecycle ownership and enable platform optimizations.

## Decision

**Managed tables in all layers**, with the per-layer container structure
preserved by giving every schema a managed location inside its layer's
container (`abfss://bronze@.../dev/managed/bronze`, etc.). The landing zone
stays raw files behind an **external volume** — files, not tables.

## Rationale

- Managed tables are the UC-recommended default: DROP cleans storage,
  predictive optimization / auto-OPTIMIZE apply, no path-permission escape
  hatch around table grants.
- The usual argument for external bronze — "other tools must read the files" —
  does not apply; every consumer goes through UC.
- Schema-level managed locations keep the per-layer container layout (and its
  lifecycle/cost policies) without external-table downsides.
- Catalog-level storage root points at the checkpoints container (`uc/<env>`)
  only as a fallback for schemas created without an explicit root.

## Consequences

- (−) Files are not at hand-picked paths; debugging goes through
  `DESCRIBE DETAIL`. Acceptable.
- (+) `terraform destroy` + `force_destroy` cleans data with the catalogs.
