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

# Read only when the human engineer's name isn't pinned: CI plans as the
# infra SP, which is not (yet) a workspace user, so identity lookups come
# from pipeline.tfvars there (same pattern as infra/core).
data "databricks_current_user" "me" {
  count = var.engineer_user_name == "" ? 1 : 0
}

locals {
  engineer_user_name = var.engineer_user_name != "" ? var.engineer_user_name : data.databricks_current_user.me[0].user_name
}

data "databricks_user" "me_account" {
  count     = local.groups_enabled ? 1 : 0
  provider  = databricks.account
  user_name = local.engineer_user_name
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

  # The workspace mirrors the Entra display name ("sp-lakeforge-dev-deploy"),
  # so this attribute drifts forever — and "fixing" it makes the provider PUT
  # the whole SCIM object, which wipes the entitlements below (took down the
  # prod job on 2026-07-05). Never reconcile display names on Entra-backed SPs.
  lifecycle {
    ignore_changes = [display_name]
  }
}

# The medallion job runs on job clusters defined in the bundle (FR-5.4);
# creating them at run time requires this entitlement on the run-as identity.
# Found on the first CI-driven run: PERMISSION_DENIED "not authorized to
# create clusters".
resource "databricks_entitlements" "deploy_ws" {
  count                = local.groups_enabled ? 0 : 1
  service_principal_id = databricks_service_principal.deploy_ws[0].id
  # Authoritative resource: list everything the SP needs, not just the delta.
  allow_cluster_create  = true
  workspace_access      = true
  databricks_sql_access = true
}

resource "databricks_service_principal" "analyst_ws" {
  count          = local.groups_enabled ? 0 : 1
  application_id = local.core.analyst_sp_client_id
  display_name   = "sp-lakeforge-analyst"

  # Same SCIM-PUT hazard as deploy_ws above.
  lifecycle {
    ignore_changes = [display_name]
  }
}

# Principal names used by grants.tf / secret_scope.tf / sql_warehouse.tf.
locals {
  engineers_principal = local.groups_enabled ? databricks_group.engineers[0].display_name : local.engineer_user_name
  analysts_principal  = local.groups_enabled ? databricks_group.analysts[0].display_name : databricks_service_principal.analyst_ws[0].application_id
  jobs_principal      = local.groups_enabled ? databricks_group.jobs[0].display_name : databricks_service_principal.deploy_ws[0].application_id

}
