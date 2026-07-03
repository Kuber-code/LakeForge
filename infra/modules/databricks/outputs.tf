output "workspace_id" {
  description = "Azure resource id of the workspace."
  value       = azurerm_databricks_workspace.this.id
}

output "workspace_numeric_id" {
  description = "Databricks workspace id (used for account-level assignments)."
  value       = azurerm_databricks_workspace.this.workspace_id
}

output "workspace_url" {
  value = "https://${azurerm_databricks_workspace.this.workspace_url}"
}
