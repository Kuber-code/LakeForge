# LakeForge — Secure Azure Lakehouse Platform

An end-to-end Azure lakehouse platform: **VNet-injected Databricks** with secure cluster connectivity, **private endpoints** for storage and Key Vault, a full **Service Principal / Managed Identity** model with OIDC federation, **Unity Catalog** governance, incremental Medallion pipelines fed from Azure SQL and ADLS Gen2, deployed with **Databricks Asset Bundles** through Azure DevOps — plus a dedicated cluster & query performance lab.

> Companion project to [BrewQuality](https://github.com/Kuber-code/BrewQuality). BrewQuality answers *"How do I guarantee data quality on a lakehouse?"* — LakeForge answers *"How do I build the secure, governed, performant Azure platform that a lakehouse runs on?"*

## Project status — complete ✅

All four phases delivered and verified end-to-end (2026-07-05):

| Phase | Delivered | Proof |
|---|---|---|
| **P1 — Foundations** | VNet-injected Databricks (NPIP), private endpoints for storage + Key Vault, SP/MI identity matrix with OIDC, Unity Catalog | `verify_p1.py`; analyst SP denied on `silver` (negative test) |
| **P2 — Data platform** | Incremental Medallion (Auto Loader files + JDBC from Azure SQL → SCD2 silver → gold star schema), quality gates | `run_p2_e2e.py` 9/9 PASS; 36 pytest on local Spark; `fact_sales` = 15 103 from both sources |
| **P3 — Orchestration + CI/CD** | DAB multi-task job (conditional gold skip), Azure DevOps CI→dev→**prod with approval**, WIF (zero secrets), gated Terraform pipeline | prod medallion job ran **unattended end-to-end** on the 05:00 cron path |
| **P4 — Performance + dashboards** | Cluster/layout/query benchmark lab (50M rows), 3 Lakeview dashboards, freshness alert, 8 ADRs | `docs/performance-findings.md` with numbers; dashboards render on serverless via **NCC private endpoints** (storage stays private); alert proven 999h→0h |

The security posture is intact throughout: storage + Key Vault are private-endpoint-only (public access denied), and even the serverless dashboard warehouse reaches the data over a Network Connectivity Config rather than any public opening. Full engineering narrative — including the production incidents fixed along the way — is in the ADRs and the git history.

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

## Running the Medallion pipelines (P2)

All pipeline logic lives in the installable package [`src/lakeforge/`](src/lakeforge/);
notebooks in [`notebooks/`](notebooks/) are thin entry points (E4). Manual run order:

```powershell
# 1. Drop distributor files into the landing volume (FR-4.1)
python seed/generate_distributor_files.py --date 2026-07-04 --out out/
databricks fs cp out/shipments_2026-07-04_1.csv dbfs:/Volumes/lakeforge_dev/bronze/landing/shipments/
databricks fs cp out/returns_2026-07-04_1.json  dbfs:/Volumes/lakeforge_dev/bronze/landing/returns/

# 2. In the workspace, run the notebooks in order (each is idempotent, FR-4.6):
#    01_bronze_files  -> Auto Loader ingest (CSV/JSON, schema evolution, rescue column)
#    02_bronze_sql    -> incremental JDBC from Azure SQL (watermark in ops.watermarks)
#    03_silver        -> dedup + typing + SCD2 customers + MERGE upserts (CDF on silver.orders)
#    04_gold          -> star schema + aggregates, then quality gates (fail -> job fails)
#    99_cdf_demo      -> read the Change Data Feed on silver.orders
```

### Unit tests (local Spark)

```bash
pip install -e ".[dev]"
pytest tests/
```

Tests run transformation logic (SCD2, MERGE upserts, gold star schema, quality
gates) on a local Delta-enabled SparkSession — no Azure required. On Windows,
local Spark needs Hadoop `winutils`; the simplest route is running pytest under
WSL (any distro with Python 3.11+ and a JDK).

## Performance lab & dashboards (P4)

The E7 lab benchmarks a 50M-row synthetic fact under five physical layouts
(small files / OPTIMIZE / Z-ORDER / liquid clustering / over-partitioning),
four cluster shapes (Photon on/off, scale-up vs scale-out), five bad-query
rewrites, and Delta maintenance (VACUUM / time travel). Every measurement
lands in `ops.benchmarks`; run it with `databricks bundle run perf_lab -t dev`.
Headline numbers and analysis: [docs/performance-findings.md](docs/performance-findings.md).

Three Lakeview dashboards deploy from [dashboards/](dashboards/) as part of
the bundle (FR-8.1..8.3): *Sales & Distribution* (gold), *Platform
Operations* (`ops` + `system.lakeflow`), *Performance & Cost*
(`ops.benchmarks` + `system.billing`). A SQL alert
([scripts/create_freshness_alert.py](scripts/create_freshness_alert.py))
notifies when gold goes stale for >24h (FR-8.4).

## Git strategy (FR-6.4)

Trunk-based development: `main` is the only long-lived branch and is always
deployable. Work happens on short-lived branches (`feat/...`, `fix/...`)
merged to `main` via pull request; the branch policy requires the CI stage of
[pipelines/ci-cd.yml](pipelines/ci-cd.yml) (ruff + pytest + `bundle validate`)
to pass before merge. Merging to `main` triggers deploy to dev; prod deploys
sit behind a manual approval on the `lakeforge-prod` environment. Terraform
changes ride their own pipeline ([pipelines/terraform.yml](pipelines/terraform.yml)):
plan on PR, approval-gated apply on `main`. Conventional Commits throughout,
one commit per functional requirement where practical.

See [docs/azure-devops-setup.md](docs/azure-devops-setup.md) for the one-time
Azure DevOps wiring (org, WIF service connections, environments, policies).

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
- [Performance findings](docs/performance-findings.md)
- [ADRs](docs/adr/)

## Delivery phases

| Phase | Scope | Status |
|---|---|---|
| P1 — Foundations (infra + identity) | E1, E2, E3 | ✅ done — exit criteria verified 2026-07-04 (`scripts/verify_p1.py`: cluster reads ADLS via the Access Connector through private endpoints; analyst SP denied on silver, allowed on gold) |
| P2 — Data platform | E4 | ✅ done — exit criteria verified 2026-07-04 (`scripts/run_p2_e2e.py` 9/9 PASS: gold star schema fed from Azure SQL *and* distributor files; SCD2 proven with a changed customer — old version closed, new current; 36 pytest green on local Spark) |
| P3 — Orchestration + CI/CD | E5, E6 | ✅ done — verified 2026-07-05: Azure DevOps run took CI → deploy dev + smoke integration test → **manual approval** → deploy prod (medallion job, 05:00 UTC cron, run-as the deploy SP); two WIF service connections (zero secrets); gated Terraform pipeline (plan on PR, approval-gated apply). The prod job later ran **unattended end-to-end** on the cron path |
| P4 — Performance lab + dashboards | E7, E8, E9 | ✅ done — verified 2026-07-05: E7 benchmark lab ran live on 50M rows (results in `ops.benchmarks`, numbers in [performance-findings](docs/performance-findings.md)); 3 Lakeview dashboards render on the serverless warehouse via **NCC private endpoints** (storage stays private-only); freshness SQL alert proven both ways (999h stale → fires, 0h fresh → clears); 8 ADRs |

Deferral note: Unity Catalog **account-level groups** (`lf_*`) are coded but applied in fallback mode (grants target the SPs directly), and the P4 **NCC** + system-schema grants were provisioned live (see [`scripts/setup_ncc.py`](scripts/setup_ncc.py)) rather than through Terraform. Both await the infra SP holding Databricks **account admin** so the account provider can manage them in CI — the account REST API historically rejected this tenant's personal Microsoft account, though as of 2026-07-05 it accepts the human's Entra token directly. Flip `enable_account_groups` / `enable_ncc` to `true` and import to converge; see [identity matrix](docs/identity-matrix.md) and [ADR-0008](docs/adr/0008-warehouse-serverless-vs-classic.md).
