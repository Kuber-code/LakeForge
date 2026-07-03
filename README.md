# LakeForge — Secure Azure Lakehouse Platform

An end-to-end Azure lakehouse platform: **VNet-injected Databricks** with secure cluster connectivity, **private endpoints** for storage and Key Vault, a full **Service Principal / Managed Identity** model with OIDC federation, **Unity Catalog** governance, incremental Medallion pipelines fed from Azure SQL and ADLS Gen2, deployed with **Databricks Asset Bundles** through Azure DevOps — plus a dedicated cluster & query performance lab.

> Companion project to [BrewQuality](https://github.com/Kuber-code/BrewQuality). BrewQuality answers *"How do I guarantee data quality on a lakehouse?"* — LakeForge answers *"How do I build the secure, governed, performant Azure platform that a lakehouse runs on?"*

## Architecture

```
                        Azure Resource Group: rg-lakeforge-dev
 ┌─────────────────────────────────────────────────────────────────────┐
 │  VNet 10.20.0.0/22                                                  │
 │  ├── snet-dbx-host      10.20.0.0/24  (Databricks host, delegated)  │
 │  ├── snet-dbx-container 10.20.1.0/24  (Databricks container, deleg.)│
 │  └── snet-privatelink   10.20.2.0/26  (private endpoints)           │
 │        ├── pe-adls-dfs / pe-adls-blob → Storage (ADLS Gen2)         │
 │        └── pe-keyvault → Key Vault                                  │
 │  NSGs on all subnets, Private DNS zones linked to VNet              │
 └─────────────────────────────────────────────────────────────────────┘
   Azure SQL DB (serverless) ──JDBC──┐
   ADLS landing container ──AutoLoader┤→ bronze → silver (SCD2) → gold
                                      Databricks (VNet-injected, NPIP)
                                      Unity Catalog · Workflows · DAB
   Azure DevOps Pipelines ──(SP/OIDC)──> terraform apply + bundle deploy
```

## Repository layout

```
lakeforge/
├── infra/
│   ├── bootstrap/          # one-time: storage account for Terraform remote state
│   ├── core/               # root stack 1: Azure resources (azurerm/azuread)
│   ├── workspace/          # root stack 2: Databricks/Unity Catalog (databricks provider)
│   └── modules/            # network, storage, keyvault, sql, databricks, identity, ...
├── src/lakeforge/          # PySpark package (P2)
├── tests/                  # pytest unit tests (P2)
├── resources/              # DAB job definitions (P3)
├── notebooks/              # thin entry points only (P2)
├── seed/                   # Azure SQL schema + synthetic data seed (P1/P2)
├── pipelines/              # Azure DevOps YAML (P3)
├── dashboards/             # Lakeview JSON exports (P4)
└── docs/                   # requirements, identity-matrix, network-design, adr/
```

Infra is split into two root stacks because the Databricks provider (Unity Catalog objects, grants, secret scopes) can only be configured once the workspace exists; `infra/workspace` reads `infra/core` outputs via remote state.

## Quickstart

Prerequisites: Azure CLI (logged in), Terraform ≥ 1.9, Databricks CLI. No secrets are stored in this repo — subscription/tenant IDs come from your environment.

```powershell
# 0. Environment (never hardcoded — public repo)
$env:ARM_SUBSCRIPTION_ID = (az account show --query id -o tsv)

# 1. One-time: create the remote-state storage account
./infra/bootstrap/bootstrap.ps1

# 2. Azure resources
cd infra/core
terraform init -backend-config="../backend.hcl"
terraform apply

# 3. Seed the OLTP database
python seed/seed_sql.py

# 4. Unity Catalog & workspace objects
cd ../workspace
terraform init -backend-config="../backend.hcl"
terraform apply
```

## Cost notes

Target burn ≤ 300 PLN (~70 EUR)/month. Main fixed cost: 3 private endpoints (~35 PLN/mo each). Everything else is on-demand: serverless Azure SQL auto-pauses after 60 min, job clusters use spot + autotermination. An Azure budget with 50/80/100% alerts is part of the Terraform stack. `terraform destroy` leaves nothing billable.

## How this differs from BrewQuality

| | BrewQuality | LakeForge |
|---|---|---|
| Focus | Data quality engine | Secure platform & infrastructure |
| Domain | IoT / sensor telemetry | Brewery sales & distribution (ERP-like SQL + file drops) |
| Networking | Managed defaults | VNet injection, NPIP, private endpoints, private DNS |
| Identity | Basic | SP/MI matrix, OIDC federation, UC grants model |
| Performance | — | Cluster & query optimization lab with benchmarks |

## Documentation

- [Requirements](docs/requirements.md)
- [Identity matrix](docs/identity-matrix.md)
- [Network design](docs/network-design.md)
- [ADRs](docs/adr/)

## Delivery phases

| Phase | Scope | Status |
|---|---|---|
| P1 — Foundations (infra + identity) | E1, E2, E3 | 🚧 in progress |
| P2 — Data platform | E4 | ⬜ |
| P3 — Orchestration + CI/CD | E5, E6 | ⬜ |
| P4 — Performance lab + dashboards | E7, E8, E9 | ⬜ |
