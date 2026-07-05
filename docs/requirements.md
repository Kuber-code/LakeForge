# LakeForge — Secure Azure Lakehouse Platform

**Project type:** Platform engineering / Data engineering portfolio project
**Companion to:** [BrewQuality](https://github.com/Kuber-code/BrewQuality) (data quality focus) — LakeForge deliberately covers everything BrewQuality does *not*
**Language:** English (code, docs, commits, dashboards)
**Tooling:** Claude Code in VS Code, Terraform, Azure CLI, Databricks CLI + Asset Bundles, Azure DevOps

---

## 1. Positioning & story

> BrewQuality answers: *"How do I guarantee data quality on a lakehouse?"*
> LakeForge answers: *"How do I build the secure, governed, performant Azure platform that a lakehouse runs on?"*

One-sentence pitch for the interview:

> "LakeForge is an end-to-end Azure lakehouse platform — VNet-injected Databricks, private endpoints, a full Service Principal / Managed Identity model, incremental Medallion pipelines fed from Azure SQL and ADLS, deployed with Databricks Asset Bundles through Azure DevOps, with a dedicated cluster & query performance lab."

### Business domain

**Brewery Sales & Distribution.** An OLTP system (Azure SQL Database) holds `customers`, `products`, `orders`, `order_lines`, `deliveries`. Distributors also drop daily CSV/JSON files (shipments, returns) into a landing zone. LakeForge ingests both into a Medallion lakehouse and serves gold-layer analytics: revenue, volume by brand/region, delivery SLA, distributor performance.

This is intentionally different from BrewQuality's IoT/sensor angle and mirrors a classic enterprise pattern: **ERP-like SQL source + file drops → lakehouse**.

---

## 2. Learning objectives (mapped to the Heineken JD)

| JD requirement | Where LakeForge covers it |
|---|---|
| Azure Key Vault | KV with RBAC, secrets for SQL + SP credentials, KV-backed Databricks secret scope, private endpoint |
| Service Principals | 2 SPs with distinct roles (infra CI/CD, bundle deploy) + OIDC/workload identity federation for pipelines |
| Managed Identities | Databricks Access Connector (UC storage credential), Azure SQL access pattern |
| Storage Accounts (ADLS Gen2) | HNS storage, containers per layer, external locations, lifecycle policy, private endpoints (dfs/blob) |
| Azure networking & infrastructure | VNet injection (host/container subnets), NSGs, private endpoint subnet, Private DNS zones, secure cluster connectivity (NPIP) |
| Delta Lake architecture | MERGE/SCD2, CDF, OPTIMIZE, Z-ORDER, liquid clustering, VACUUM, time travel, schema evolution |
| Workflows & job orchestration | Multi-task job with dependencies, retries, schedule + file-arrival trigger, task values, notifications |
| Databricks Asset Bundles | dev/prod targets, variables, substitutions, job cluster definitions in bundle |
| Cluster configuration & optimization | Performance lab: node types, autoscaling, Photon, spot, single-node vs multi-node benchmarks |
| Unity Catalog | Metastore objects, catalogs per env, external locations, volumes, groups & grants matrix, lineage, system tables |
| Python / PySpark | All pipeline code in PySpark modules + unit tests |
| Advanced SQL & validation logic | Window functions, MERGE, query profiles, EXPLAIN, join strategy analysis, data validation views |
| Medallion architecture | bronze → silver → gold with clear contracts per layer |
| CI/CD, Azure Pipelines, Git | Azure DevOps multi-stage YAML pipeline: lint → test → validate → deploy dev → integration test → approval → deploy prod |

---

## 3. Architecture overview

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

---

## 4. Functional requirements by epic

### E1 — Infrastructure as Code (Terraform)

All Azure resources are created by Terraform (azurerm + databricks providers). No click-ops except the initial subscription and the Azure DevOps org.

- **FR-1.1** Remote state in a dedicated storage account (bootstrap script allowed).
- **FR-1.2** VNet `10.20.0.0/22` with three subnets: Databricks host (public subnet in Databricks terms), Databricks container (private), and a private-endpoint subnet. Host/container subnets delegated to `Microsoft.Databricks/workspaces`.
- **FR-1.3** NSG per Databricks subnet with the required Databricks rules; a restrictive NSG on the private-endpoint subnet.
- **FR-1.4** ADLS Gen2 storage account (HNS enabled), containers: `landing`, `bronze`, `silver`, `gold`, `checkpoints`. Lifecycle rule: `landing` blobs → cool tier after 7 days.
- **FR-1.5** Azure Key Vault in RBAC authorization mode.
- **FR-1.6** Azure SQL Server + serverless database (GP_S_Gen5_1, auto-pause 60 min) — the OLTP source. Seed schema + data via an idempotent Python/SQL script.
- **FR-1.7** Databricks workspace: **VNet injection** + **secure cluster connectivity (NPIP)**. Premium tier (required for UC).
- **FR-1.8** Private endpoints + Private DNS zones for: storage `dfs`, storage `blob`, Key Vault. Public network access on storage/KV disabled after PE validation (two-step: deploy open → flip to private; document the flip).
- **FR-1.9** Databricks Access Connector (system-assigned managed identity) with `Storage Blob Data Contributor` on the storage account.
- **FR-1.10** Azure Budget (300 PLN) with alert at 50/80/100%. Teardown: `terraform destroy` must leave nothing billable.

**Acceptance:** `terraform plan` clean on second run (idempotent); workspace reachable; storage/KV reachable **only** through private endpoints from the workspace; a diagram in README matches deployed reality.

### E2 — Identity & access model

The showpiece epic. Deliverable includes an **identity matrix** (`docs/identity-matrix.md`): *who / what type / what scope / why / how credentials flow*.

- **FR-2.1** `sp-lakeforge-infra` — Service Principal used by Azure DevOps for Terraform (Contributor on the RG + User Access Administrator where needed). Authenticated via **workload identity federation (OIDC)** — no client secrets in DevOps.
- **FR-2.2** `sp-lakeforge-deploy` — Service Principal added to the Databricks workspace (service principal entity), used by the pipeline for `databricks bundle deploy` and as the **run-as identity** of prod jobs.
- **FR-2.3** Access Connector **managed identity** → UC storage credential → external locations for each container. Explain in docs why MI beats SP+secret for storage access.
- **FR-2.4** Key Vault secrets: SQL connection credentials. Databricks reads them via a **Key Vault-backed secret scope**. No secret value ever appears in code, DAB config, or pipeline variables.
- **FR-2.5** Unity Catalog groups: `lf_engineers` (full dev catalog), `lf_analysts` (SELECT on gold only), `lf_jobs` (the deploy SP; owns prod pipelines). Grants applied via Terraform or SQL scripts kept in repo. Include a negative test: analyst identity cannot read silver.
- **FR-2.6** Document (not necessarily implement) the alternative: Lakehouse Federation / MI-based auth to Azure SQL vs JDBC + KV secret, with trade-offs.

**Acceptance:** pipeline runs with zero stored secrets for Azure auth; grants matrix verified by executing queries as different principals; identity matrix doc complete.

### E3 — Unity Catalog layout

- **FR-3.1** Catalogs `lakeforge_dev` and `lakeforge_prod`; schemas `bronze`, `silver`, `gold`, `ops` in each.
- **FR-3.2** External locations bound to containers; managed tables in silver/gold, external or managed in bronze (choose and justify).
- **FR-3.3** One UC **Volume** for the landing files consumed by Auto Loader.
- **FR-3.4** Table comments + tags (`layer`, `owner`, `pii=false`) on every table; show lineage graph for a gold table in docs (screenshot).
- **FR-3.5** `ops` schema hosts run logs, benchmark results, freshness metrics.

### E4 — Ingestion & Medallion pipelines (PySpark)

Code as installable Python package (`src/lakeforge/...`), notebooks only as thin entry points. Unit tests with pytest (local SparkSession) for transformation logic.

- **FR-4.1 Bronze / files:** Auto Loader (`cloudFiles`) incrementally ingests distributor CSV/JSON from the landing volume; `_ingest_ts`, `_source_file`, rescue data column; schema evolution enabled; checkpoint in `checkpoints` container.
- **FR-4.2 Bronze / SQL:** incremental JDBC extract from Azure SQL using a watermark (`modified_at`) stored in `ops.watermarks`; append to bronze with load metadata.
- **FR-4.3 Silver:** dedup, typing, referential checks; **SCD Type 2** for `dim_customer` via `MERGE INTO` (track `valid_from/valid_to/is_current`); orders upserted by `MERGE`. Enable **Change Data Feed** on one silver table and demonstrate reading it.
- **FR-4.4 Gold:** star schema — `fact_sales`, `dim_customer`, `dim_product`, `dim_date` + two aggregate tables for dashboards (daily revenue by brand/region, delivery SLA).
- **FR-4.5** Basic quality gates (row counts, PK uniqueness, null thresholds) logged to `ops.pipeline_runs` — lightweight on purpose; deep DQ lives in BrewQuality and you say so in docs.
- **FR-4.6** Idempotency requirement: re-running any task must not duplicate data.

### E5 — Workflows & orchestration

- **FR-5.1** One multi-task Databricks Job: `ingest_files` and `ingest_sql` in parallel → `silver` → `gold` → `refresh_metrics`; `depends_on` wiring; per-task retries (2, exponential); timeout; email/webhook notification on failure.
- **FR-5.2** Two triggers demonstrated: cron schedule (prod) and **file-arrival trigger** on the landing location (dev).
- **FR-5.3** Use **task values** to pass the watermark/run stats between tasks; one **conditional (if/else) task**: skip gold refresh when silver row delta = 0.
- **FR-5.4** Jobs run on **job clusters defined in the bundle** (not all-purpose), pinned Spark version, spot instances with fallback, autotermination.

### E6 — Databricks Asset Bundles + Azure DevOps CI/CD

- **FR-6.1** `databricks.yml` with `dev` and `prod` targets: different catalogs, cluster sizes, schedule paused in dev, `run_as` the deploy SP in prod; variables + substitutions used throughout.
- **FR-6.2** Azure DevOps multi-stage YAML pipeline:
  1. **CI:** ruff + pytest (unit) + `databricks bundle validate`
  2. **Deploy dev:** `bundle deploy -t dev` + run smoke job + integration assertion (gold row count > 0)
  3. **Gate:** manual approval (environment check)
  4. **Deploy prod:** `bundle deploy -t prod`
- **FR-6.3** Terraform gets its own pipeline (plan on PR, apply on main with approval).
- **FR-6.4** Branch policy on `main`: PR required, pipeline must pass. Document the Git strategy (trunk-based) in README.
- **FR-6.5** Service connections use workload identity federation (ties into FR-2.1/2.2).

### E7 — Performance & cluster optimization lab

The strongest interview differentiator. All experiments produce rows in `ops.benchmarks` (scenario, cluster config, duration, bytes read/shuffled, cost estimate) and a written `docs/performance-findings.md`.

- **FR-7.1** Generate a synthetic large fact table (~50–100M rows) with a PySpark data generator.
- **FR-7.2 Cluster experiments** (same workload, varying config): single-node vs 2-worker; Photon on vs off; spot vs on-demand cost math; autoscaling behavior under a skewed job. Record DBU + VM cost per run.
- **FR-7.3 Layout experiments** on the big table: baseline (many small files) vs `OPTIMIZE` vs `OPTIMIZE ZORDER BY` vs **liquid clustering** (`CLUSTER BY`); measure a selective query on each. Include the small-files problem demo and the over-partitioning anti-pattern.
- **FR-7.4 Query optimization:** take two deliberately bad SQL queries (exploding join, non-sargable filter, needless DISTINCT), analyze with `EXPLAIN` + Spark UI / query profile (scan, shuffle, spill), rewrite, document before/after. Cover broadcast vs shuffle join and AQE effects.
- **FR-7.5** Delta maintenance: VACUUM (retention trade-offs), time travel demo, `DESCRIBE HISTORY` forensics.

### E8 — Dashboards (Lakeview / AI-BI, min. 3)

- **FR-8.1 Sales & Distribution (business):** revenue/volume by brand & region, top distributors, delivery SLA trend — on gold aggregates.
- **FR-8.2 Platform operations:** job run history & duration trend (system tables `system.lakeflow`/jobs), data freshness per layer, rows ingested per run, failure log — on `ops` + system tables.
- **FR-8.3 Performance & cost:** benchmark results comparison, DBU consumption from `system.billing.usage`, cost per pipeline run estimate.
- **FR-8.4** One SQL Alert: gold freshness > 24h → notification.

### E9 — Documentation (all in English)

- **FR-9.1** README: architecture diagram, quickstart, cost notes, "how this differs from BrewQuality".
- **FR-9.2** `docs/identity-matrix.md`, `docs/network-design.md` (why VNet injection, why NPIP, packet path through private endpoints, what SCC changes), `docs/performance-findings.md`.
- **FR-9.3** ADRs (5–8 short ones): VNet injection vs managed default; MI vs SP for storage; JDBC vs Federation; Z-ORDER vs liquid clustering; DAB vs Terraform for jobs; job clusters vs serverless.

---

## 5. Non-functional requirements

- **NFR-1 Security:** zero secrets in Git, DAB files, or pipeline variables; KV + OIDC only. Storage & KV public access disabled at the end state.
- **NFR-2 Cost:** hard controls — job clusters with spot + autotermination ≤ 15 min, SQL auto-pause, Azure budget alerts, `make destroy` teardown, and a habit: destroy compute-heavy infra between sessions (Terraform brings it back in ~15 min). Target burn: **≤ 300 PLN/month** (private endpoints ≈ 3 × ~35 PLN/mo are the main fixed cost; the rest is on-demand).
- **NFR-3 Reproducibility:** anyone with a subscription can stand it up: `bootstrap → terraform apply → seed → bundle deploy → run job`.
- **NFR-4 Code quality:** ruff + pytest in CI, type hints in `src/`, conventional commits.
- **NFR-5 Idempotency:** every pipeline task and every seed/infra script re-runnable safely.

---

## 6. Phased delivery plan

**All phases delivered and verified 2026-07-05.**

| Phase | Scope | Exit criteria | Status |
|---|---|---|---|
| **P1 — Foundations (infra + identity)** | E1, E2, E3; workspace up, UC wired, identity matrix written | Cluster reads a file from ADLS through the Access Connector; analyst SP denied on silver | ✅ verified (`scripts/verify_p1.py`) |
| **P2 — Data platform** | E4; medallion end-to-end run manually | Gold star schema populated from both sources; SCD2 verified with a changed customer record | ✅ verified (`scripts/run_p2_e2e.py` 9/9 PASS; 36 pytest) |
| **P3 — Orchestration + CI/CD** | E5, E6 | Green Azure DevOps run deploys dev→prod with approval; scheduled job succeeds unattended | ✅ verified (ci-cd dev→prod w/ approval; prod medallion run SUCCESS end-to-end) |
| **P4 — Performance lab + dashboards** | E7, E8, E9 | 3 dashboards live; performance findings doc with numbers; alert fires on stale data test | ✅ verified (3 Lakeview dashboards render via NCC; `docs/performance-findings.md`; freshness alert proven 999h→0h) |

---

## 7. Repository layout

```
lakeforge/
├── infra/                  # Terraform (modules: network, storage, keyvault, sql, databricks, identity)
├── src/lakeforge/          # PySpark package: ingest/, transform/, quality/, benchmark/, utils/
├── tests/                  # pytest unit tests (local Spark)
├── resources/              # DAB job & pipeline definitions (YAML)
├── notebooks/              # thin entry points only
├── seed/                   # Azure SQL schema + synthetic data generators
├── pipelines/              # Azure DevOps YAML (ci.yml, cd.yml, terraform.yml)
├── dashboards/             # exported Lakeview JSON definitions
├── docs/                   # identity-matrix, network-design, performance-findings, adr/
├── databricks.yml
└── README.md
```

---

## 8. Interview leverage (how to talk about it)

- **Networking question →** "In LakeForge I VNet-injected the workspace with NPIP and moved storage and Key Vault behind private endpoints — I can walk through the DNS resolution path."
- **Identity question →** open the identity matrix: two SPs with distinct blast radii, OIDC federation instead of secrets, MI via Access Connector for storage.
- **Cluster/optimization question →** quote your own benchmark numbers: Photon speedup, Z-ORDER vs liquid clustering on a selective query, the small-files demo.
- **DAB/CI-CD question →** dev/prod targets, `run_as` service principal, approval-gated Azure DevOps stages.
- **Paired story:** *"BrewQuality is my data-quality engine; LakeForge is the secure platform underneath. Together they cover the whole JD."*
