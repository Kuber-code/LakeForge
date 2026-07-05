# ADR-0008: Dashboard warehouse — serverless + NCC private endpoints

**Status:** accepted (P4), implemented 2026-07-05 · **Related:** FR-8.1..8.4, FR-1.8, FR-9.3

## Context

Lakeview dashboards (E8) can only query through a SQL warehouse. The existing
`wh-lakeforge` is **serverless**, and since the FR-1.8 network flip (storage +
Key Vault public access disabled) serverless compute cannot reach the
lakehouse data: it runs in Databricks' account network and needs **NCC private
endpoints** to cross into private storage. Two unblock paths exist:

1. **NCC private endpoints** for serverless — an account-level object holding
   Databricks-managed private endpoints into our storage, bound to the
   workspace. Requires Databricks account API access, historically blocked for
   this tenant's MSA identity.
2. **Classic (pro) warehouse** — runs in the customer VNet like the job
   clusters. Measured 2026-07-05 by launching one: a 2X-Small provisions
   **2× Standard_E8ds_v4 = 16 vCPU in the `standardEDSv4Family`**. That family
   is capped at 10 in westeurope (one node comes up at usage 8, the second
   fails `AZURE_QUOTA_EXCEEDED_EXCEPTION`). The regional total was raised to 24
   but that is not the binding limit — the **per-family EDSv4 cap** is, and
   `az quota update` on it returns `ContactSupport` (needs a portal ticket:
   Quotas → Compute → "Standard EDSv4 Family vCPUs" / westeurope → 16).

## Decision

**Keep serverless and give it an NCC** — the preferred path, implemented
2026-07-05. The EDSv4 quota ticket for the classic fallback was auto-rejected
(and a Poland Central grant is useless — the warehouse must run in the
workspace's region, westeurope). At the same time the account API began
accepting the human's Entra token (`az account get-access-token --resource
2ff814a6-...`), so the NCC was created directly: NCC `ncc-lakeforge-we`
(westeurope) + `dfs`/`blob` private-endpoint rules into `stlakeforgedevsh93zt`,
bound to the workspace, connections approved on the storage side. Verified:
the serverless warehouse reads a private-storage Delta table (46 rows). All
three dashboards and the freshness alert now work with FR-1.8's
public-access-denied posture fully intact.

Provisioning is captured in `scripts/setup_ncc.py` (runbook) and, as IaC,
`infra/workspace/ncc.tf` behind `var.enable_ncc` (default false) — the NCC uses
the account provider, so Terraform can only own it once the infra SP is an
account admin (same gate as `var.enable_account_groups`); until then the live
objects are managed out-of-band with import ids recorded in `ncc.tf`.

The classic warehouse stays documented as a fallback via
`var.warehouse_serverless = false`, should serverless NCC ever be unavailable.

## Rationale & trade-offs

- Opening storage to public access to feed dashboards would undo FR-1.8 and
  the network design — never an option.
- NCC keeps the zero-idle-cost serverless model; a classic warehouse would
  idle at 16-vCPU cost for a workload measured in minutes/day. NCC private
  endpoints add ~a few EUR/mo — cheaper and the correct architecture.
- The account-API unblock has a bonus: account-level groups (FR-2.5) and
  `system.*` schema grants (the cost/ops dashboard's billing panels) are now
  reachable through the same credential path.
