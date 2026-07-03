# FR-2.4 — Key Vault-backed secret scope: Databricks never stores the SQL
# credentials, it reads them from KV at runtime. Secret values exist only in
# Key Vault; code references them as dbutils.secrets.get("kv-lakeforge", ...).

resource "databricks_secret_scope" "kv" {
  name = "kv-lakeforge"

  keyvault_metadata {
    resource_id = local.core.key_vault_id
    dns_name    = local.core.key_vault_uri
  }

  depends_on = [databricks_metastore_assignment.this]
}

# In fallback mode the human engineer is the scope creator (implicit MANAGE),
# so only the group needs an explicit ACL in group mode.
resource "databricks_secret_acl" "engineers_read" {
  count = local.groups_enabled ? 1 : 0

  scope      = databricks_secret_scope.kv.name
  principal  = local.engineers_principal
  permission = "READ"

  depends_on = [databricks_mws_permission_assignment.groups]
}

resource "databricks_secret_acl" "jobs_read" {
  scope      = databricks_secret_scope.kv.name
  principal  = local.jobs_principal
  permission = "READ"

  depends_on = [
    databricks_mws_permission_assignment.groups,
    databricks_service_principal.deploy_ws,
  ]
}
