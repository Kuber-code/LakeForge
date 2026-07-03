# FR-2.5 — identities inside Databricks.
#
# Two modes (var.enable_account_groups):
#   true  — target state: account-level groups + memberships + workspace
#           assignments via the account provider (needs account admin)
#   false — MSA fallback: SPs registered via workspace SCIM (works for any
#           workspace admin on an identity-federated workspace); UC grants
#           in grants.tf then target the SPs directly

locals {
  groups_enabled = var.enable_account_groups
}

# ── account mode ───────────────────────────────────────────────────────────

resource "databricks_group" "engineers" {
  count        = local.groups_enabled ? 1 : 0
  provider     = databricks.account
  display_name = "lf_engineers"
}

resource "databricks_group" "analysts" {
  count        = local.groups_enabled ? 1 : 0
  provider     = databricks.account
  display_name = "lf_analysts"
}

resource "databricks_group" "jobs" {
  count        = local.groups_enabled ? 1 : 0
  provider     = databricks.account
  display_name = "lf_jobs"
}

data "databricks_current_user" "me" {}

data "databricks_user" "me_account" {
  count     = local.groups_enabled ? 1 : 0
  provider  = databricks.account
  user_name = data.databricks_current_user.me.user_name
}

resource "databricks_service_principal" "deploy_account" {
  count          = local.groups_enabled ? 1 : 0
  provider       = databricks.account
  application_id = local.core.deploy_sp_client_id
  display_name   = "sp-lakeforge-deploy"
}

resource "databricks_service_principal" "analyst_account" {
  count          = local.groups_enabled ? 1 : 0
  provider       = databricks.account
  application_id = local.core.analyst_sp_client_id
  display_name   = "sp-lakeforge-analyst"
}

resource "databricks_group_member" "me_engineer" {
  count     = local.groups_enabled ? 1 : 0
  provider  = databricks.account
  group_id  = databricks_group.engineers[0].id
  member_id = data.databricks_user.me_account[0].id
}

resource "databricks_group_member" "deploy_jobs" {
  count     = local.groups_enabled ? 1 : 0
  provider  = databricks.account
  group_id  = databricks_group.jobs[0].id
  member_id = databricks_service_principal.deploy_account[0].id
}

resource "databricks_group_member" "analyst_analysts" {
  count     = local.groups_enabled ? 1 : 0
  provider  = databricks.account
  group_id  = databricks_group.analysts[0].id
  member_id = databricks_service_principal.analyst_account[0].id
}

resource "databricks_mws_permission_assignment" "groups" {
  for_each = local.groups_enabled ? {
    engineers = databricks_group.engineers[0].id
    analysts  = databricks_group.analysts[0].id
    jobs      = databricks_group.jobs[0].id
  } : {}
  provider = databricks.account

  workspace_id = local.core.databricks_workspace_numeric_id
  principal_id = each.value
  permissions  = ["USER"]

  depends_on = [databricks_metastore_assignment.this]
}

# ── workspace (MSA fallback) mode ──────────────────────────────────────────
# On an identity-federated workspace, SCIM SP creation by a workspace admin
# also registers the SP for this workspace — no account admin needed.

resource "databricks_service_principal" "deploy_ws" {
  count          = local.groups_enabled ? 0 : 1
  application_id = local.core.deploy_sp_client_id
  display_name   = "sp-lakeforge-deploy"
}

resource "databricks_service_principal" "analyst_ws" {
  count          = local.groups_enabled ? 0 : 1
  application_id = local.core.analyst_sp_client_id
  display_name   = "sp-lakeforge-analyst"
}

# Principal names used by grants.tf / secret_scope.tf / sql_warehouse.tf.
locals {
  engineers_principal = local.groups_enabled ? databricks_group.engineers[0].display_name : data.databricks_current_user.me.user_name
  analysts_principal  = local.groups_enabled ? databricks_group.analysts[0].display_name : databricks_service_principal.analyst_ws[0].application_id
  jobs_principal      = local.groups_enabled ? databricks_group.jobs[0].display_name : databricks_service_principal.deploy_ws[0].application_id

}
