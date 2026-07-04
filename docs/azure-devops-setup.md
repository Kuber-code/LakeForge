# Azure DevOps one-time setup (P3 / E6)

Everything in this checklist is deliberate click-ops (the requirements allow
exactly two: the subscription and the Azure DevOps org). All names below are
referenced verbatim by [pipelines/ci-cd.yml](../pipelines/ci-cd.yml) and
[pipelines/terraform.yml](../pipelines/terraform.yml) — keep them as written.

## 1. Organization + project

1. https://aex.dev.azure.com → create organization (e.g. `kuber-code`),
   region Europe.
2. Create project **LakeForge** (private, Git).

## 2. Import the repository

Repos → Import → `https://github.com/Kuber-code/LakeForge.git`.
(Keeping GitHub as the public mirror is fine: add an Azure Repos remote and
push to both, or make Azure Repos the origin and mirror to GitHub.)

## 3. Service connections (workload identity federation, FR-6.5)

Project settings → Service connections → New → **Azure Resource Manager** →
**Workload identity federation (manual)**. Create **two**:

| Name | Service principal (existing app) | Used by |
|---|---|---|
| `lakeforge-azure` | `sp-lakeforge-infra` (app id `a4264d6b-e789-4a9d-ae6a-7ee2377ae84b`) | terraform.yml |
| `lakeforge-databricks` | `sp-lakeforge-deploy` (app id `01e809d3-c4ad-43a2-8896-fa9be16a71a6`) | ci-cd.yml (bundle) |

For each connection the wizard shows an **issuer** and a **subject
identifier**. Add them as a federated credential on the matching app
(replace ISSUER/SUBJECT, run once per connection):

```powershell
az ad app federated-credential create --id a4264d6b-e789-4a9d-ae6a-7ee2377ae84b --parameters '{
  "name": "devops-lakeforge-azure",
  "issuer": "<ISSUER from the wizard>",
  "subject": "<SUBJECT from the wizard>",
  "audiences": ["api://AzureADTokenExchange"]
}'

az ad app federated-credential create --id 01e809d3-c4ad-43a2-8896-fa9be16a71a6 --parameters '{
  "name": "devops-lakeforge-databricks",
  "issuer": "<ISSUER from the wizard>",
  "subject": "<SUBJECT from the wizard>",
  "audiences": ["api://AzureADTokenExchange"]
}'
```

Then click **Verify and save** in the wizard. Scope: subscription
`eaba166a-…`, no need to grant new Azure roles — `sp-lakeforge-infra`
already holds Contributor/UAA on the RG and the tfstate role;
`sp-lakeforge-deploy` intentionally has **zero** Azure RBAC (it only needs
an Entra token to talk to Databricks).

> `sp-lakeforge-deploy` must be able to deploy bundles: it is already a
> workspace service principal; give it CAN_MANAGE on the prod bundle root if
> prod deploys fail on permissions.

## 4. Variable group

Pipelines → Library → Variable group **`lakeforge`** (non-secret values):

| Variable | Value |
|---|---|
| `DATABRICKS_HOST` | `https://adb-7405607941001785.5.azuredatabricks.net` |
| `WAREHOUSE_ID` | `25e5ba038b3f5267` |

## 5. Environments (approval gates)

Pipelines → Environments → create:

- **`lakeforge-prod`** → Approvals and checks → Approvals → add yourself.
- **`lakeforge-infra`** → same.

## 6. Pipelines

Pipelines → New pipeline → Azure Repos Git → LakeForge → Existing YAML:

1. `/pipelines/ci-cd.yml` → name it `lakeforge-ci-cd`.
2. `/pipelines/terraform.yml` → name it `lakeforge-terraform`.

First run of each will prompt to authorize the service connections and the
variable group — allow.

## 7. Branch policy on `main` (FR-6.4)

Repos → Branches → `main` → Branch policies:

- Require a minimum number of reviewers: 1 (allow requestors to approve
  their own changes — solo project).
- Build validation: add `lakeforge-ci-cd` (the CI stage runs on PRs).

## 8. Terraform backend for pipelines

The pipelines read `infra/backend.hcl`, which is gitignored (it names the
state storage account). Either commit a `backend.hcl` to Azure Repos only,
or add a pipeline step that writes it from variable-group values before
`terraform init`. The state SA is `stlakeforgetf467af950` in
`rg-lakeforge-tfstate`.

## Done when

`git push` to a feature branch + PR → CI green → merge → dev deploy + smoke
job + gold-count assert green → approval e-mail → approve → prod deploy
green, and the prod job's cron trigger (daily 05:00 UTC) runs unattended —
that is the P3 exit criterion.
