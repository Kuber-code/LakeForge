output "access_connector_id" {
  value = azurerm_databricks_access_connector.uc.id
}

output "access_connector_principal_id" {
  value = azurerm_databricks_access_connector.uc.identity[0].principal_id
}

output "infra_sp_client_id" {
  value = azuread_application.infra.client_id
}

output "deploy_sp_client_id" {
  value = azuread_application.deploy.client_id
}

output "deploy_sp_object_id" {
  value = azuread_service_principal.deploy.object_id
}

output "analyst_sp_client_id" {
  value = azuread_application.analyst.client_id
}

output "analyst_sp_object_id" {
  value = azuread_service_principal.analyst.object_id
}
