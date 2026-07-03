# Consumed by infra/workspace via terraform_remote_state and by humans/scripts.

output "resource_group_name" {
  value = azurerm_resource_group.this.name
}

output "location" {
  value = var.location
}

output "storage_account_name" {
  value = module.storage.storage_account_name
}

output "key_vault_name" {
  value = module.keyvault.key_vault_name
}

output "key_vault_id" {
  value = module.keyvault.key_vault_id
}

output "key_vault_uri" {
  value = module.keyvault.key_vault_uri
}

output "sql_server_fqdn" {
  value = module.sql.sql_server_fqdn
}

output "sql_database_name" {
  value = module.sql.database_name
}

output "databricks_workspace_url" {
  value = module.databricks.workspace_url
}

output "databricks_workspace_id" {
  value = module.databricks.workspace_id
}

output "databricks_workspace_numeric_id" {
  value = module.databricks.workspace_numeric_id
}

output "access_connector_id" {
  value = module.identity.access_connector_id
}

output "deploy_sp_client_id" {
  value = module.identity.deploy_sp_client_id
}

output "analyst_sp_client_id" {
  value = module.identity.analyst_sp_client_id
}

output "infra_sp_client_id" {
  value = module.identity.infra_sp_client_id
}

output "nat_egress_ip" {
  value = module.network.nat_egress_ip
}
