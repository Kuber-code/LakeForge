# FR-2.5 — account-level groups (workspace-local groups cannot receive UC
# grants), service principals registered at account level, and workspace
# assignments.

resource "databricks_group" "engineers" {
  provider     = databricks.account
  display_name = "lf_engineers"
}

resource "databricks_group" "analysts" {
  provider     = databricks.account
  display_name = "lf_analysts"
}

resource "databricks_group" "jobs" {
  provider     = databricks.account
  display_name = "lf_jobs"
}

# The deploying human = first engineer.
data "databricks_current_user" "me" {}

data "databricks_user" "me_account" {
  provider  = databricks.account
  user_name = data.databricks_current_user.me.user_name
}

# FR-2.2 — deploy SP as a Databricks service principal entity.
resource "databricks_service_principal" "deploy" {
  provider       = databricks.account
  application_id = local.core.deploy_sp_client_id
  display_name   = "sp-lakeforge-deploy"
}

resource "databricks_service_principal" "analyst" {
  provider       = databricks.account
  application_id = local.core.analyst_sp_client_id
  display_name   = "sp-lakeforge-analyst"
}

resource "databricks_group_member" "me_engineer" {
  provider  = databricks.account
  group_id  = databricks_group.engineers.id
  member_id = data.databricks_user.me_account.id
}

resource "databricks_group_member" "deploy_jobs" {
  provider  = databricks.account
  group_id  = databricks_group.jobs.id
  member_id = databricks_service_principal.deploy.id
}

resource "databricks_group_member" "analyst_analysts" {
  provider  = databricks.account
  group_id  = databricks_group.analysts.id
  member_id = databricks_service_principal.analyst.id
}

# Give the groups access to this workspace.
resource "databricks_mws_permission_assignment" "groups" {
  for_each = {
    engineers = databricks_group.engineers.id
    analysts  = databricks_group.analysts.id
    jobs      = databricks_group.jobs.id
  }
  provider = databricks.account

  workspace_id = local.core.databricks_workspace_numeric_id
  principal_id = each.value
  permissions  = ["USER"]

  depends_on = [databricks_metastore_assignment.this]
}
