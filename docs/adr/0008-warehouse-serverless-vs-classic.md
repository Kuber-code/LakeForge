# ADR-0008: Dashboard warehouse — serverless now, unblock path documented

**Status:** accepted (P4) · **Related:** FR-8.1..8.4, FR-1.8, FR-9.3

## Context

Lakeview dashboards (E8) can only query through a SQL warehouse. The existing
`wh-lakeforge` is **serverless**, and since the FR-1.8 network flip (storage +
Key Vault public access disabled) serverless compute cannot reach the
lakehouse data: it runs in Databricks' account network and needs **NCC private
endpoints** to cross into private storage. Two unblock paths exist:

1. **NCC private endpoints** for serverless — requires Databricks account
   console/API access, currently blocked for this tenant's MSA identity
   (documented in `docs/identity-matrix.md`).
2. **Classic (pro) warehouse** — runs in the customer VNet like the job
   clusters. Smallest size (2X-Small) needs **16 vCPUs** (E8ds_v4 driver +
   worker); the subscription's westeurope quota is **10 vCPUs total**, so this
   requires a quota increase first.

## Decision

Keep the serverless warehouse and deploy the dashboards against it **now**:
the Performance & Cost dashboard reads `system.*` tables (Databricks-managed
storage) and renders immediately; the business and operations dashboards are
complete-but-dark until one unblock path lands. **Preferred path: NCC private
endpoints** once account access is fixed — it keeps the zero-idle-cost
serverless model and also unblocks account-level groups (FR-2.5 target mode).
Quota bump + classic warehouse is the fallback if account access stays broken.

## Rationale & trade-offs

- Opening storage to public access to feed dashboards would undo FR-1.8 and
  the network design — not an option.
- A classic warehouse would idle at 16 vCPU cost characteristics for a
  portfolio workload measured in minutes/day; serverless bills only per query.
- Deploying dashboards dark is deliberate: the JSON is code-reviewed, CI/CD
  deploys it, and the fix is purely a platform change — no dashboard rework.
