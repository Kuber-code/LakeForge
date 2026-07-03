# FR-1.9 / FR-2.3 — Databricks Access Connector with a system-assigned managed
# identity. Unity Catalog uses it as the storage credential: no secret to
# create, rotate, leak or expire — Azure issues tokens for the identity at
# runtime (see docs/identity-matrix.md for the MI-vs-SP rationale).

resource "azurerm_databricks_access_connector" "uc" {
  name                = "ac-${var.base}"
  resource_group_name = var.resource_group_name
  location            = var.location

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}

resource "azurerm_role_assignment" "uc_storage" {
  scope                = var.storage_account_id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_databricks_access_connector.uc.identity[0].principal_id
}
