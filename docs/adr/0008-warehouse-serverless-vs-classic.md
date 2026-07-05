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
   clusters. Measured 2026-07-05 by launching one: a 2X-Small provisions
   **2× Standard_E8ds_v4 = 16 vCPU in the `standardEDSv4Family`**. That family
   is capped at 10 in westeurope (one node comes up at usage 8, the second
   fails `AZURE_QUOTA_EXCEEDED_EXCEPTION`). The regional total was raised to 24
   but that is not the binding limit — the **per-family EDSv4 cap** is, and
   `az quota update` on it returns `ContactSupport` (needs a portal ticket:
   Quotas → Compute → "Standard EDSv4 Family vCPUs" / westeurope → 16).

## Decision

Keep the serverless warehouse and deploy the dashboards against it **now**:
the Performance & Cost dashboard reads `system.*` tables (Databricks-managed
storage) and renders immediately; the business and operations dashboards are
complete-but-dark until one unblock path lands. **Preferred path: NCC private
endpoints** once account access is fixed — it keeps the zero-idle-cost
serverless model and also unblocks account-level groups (FR-2.5 target mode).
Quota bump + classic warehouse is the fallback if account access stays broken.

The switch itself is a single config flip: `var.warehouse_serverless = false`
in `infra/workspace` then `terraform apply` rebuilds `wh-lakeforge` as a
VNet-resident classic warehouse. Gate that flip on the EDSv4 quota ticket —
applying it before the quota lands leaves a warehouse that cannot start.

## Rationale & trade-offs

- Opening storage to public access to feed dashboards would undo FR-1.8 and
  the network design — not an option.
- A classic warehouse would idle at 16 vCPU cost characteristics for a
  portfolio workload measured in minutes/day; serverless bills only per query.
- Deploying dashboards dark is deliberate: the JSON is code-reviewed, CI/CD
  deploys it, and the fix is purely a platform change — no dashboard rework.
