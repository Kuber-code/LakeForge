# ADR-0006: Asset Bundles own jobs & dashboards, Terraform owns the platform

**Status:** accepted (P3) · **Related:** FR-6.1, FR-9.3

## Context

Both Terraform (databricks provider) and Databricks Asset Bundles (DAB) can
declare jobs, dashboards and other workspace objects. LakeForge already uses
Terraform for infrastructure (E1) and workspace/identity plumbing (E2/E3), so
jobs could have gone either way.

## Decision

A hard split by change cadence and blast radius:

- **Terraform** (`infra/core`, `infra/workspace`): everything with security or
  cost blast radius — network, storage, Key Vault, workspace, warehouse, Unity
  Catalog objects, grants, service principals, cluster policies.
- **DAB** (`databricks.yml` + `resources/*.yml`): everything that changes with
  the code — jobs, their clusters, notebooks, wheels, Lakeview dashboards.

## Rationale & trade-offs

- Jobs change with every pipeline PR; platform changes are rare and gated. One
  repo-wide Terraform state would drag job edits through the infra approval
  gate (and its plan noise) for no risk reduction.
- DAB's `mode: development`/`production` gives per-target behavior (paused
  triggers, user-prefixed names, `run_as` the deploy SP) that Terraform would
  need hand-rolled variables for; bundle deploys are also what the CI SP does
  cheaply on hosted agents — no Terraform install, no state storage access.
- The medallion job's DAG, retries and task values live next to the notebooks
  they orchestrate — reviewable in one diff.
- Trade-off: two deployment tools and two sources of truth. Mitigated by the
  split being by object type (no object is managed by both) and by CI running
  both paths: `terraform plan` for the platform, `bundle deploy` for code.
