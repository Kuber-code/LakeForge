# FR-1.5 — Key Vault in RBAC authorization mode (no access policies).
# Secrets: SQL credentials (written by the sql module), consumed by Databricks
# through a Key Vault-backed secret scope (FR-2.4).

resource "azurerm_key_vault" "this" {
  # kv- + base + suffix, max 24 chars
  name                = substr("kv-${var.base}-${var.suffix}", 0, 24)
  resource_group_name = var.resource_group_name
  location            = var.location
  tenant_id           = var.tenant_id
  sku_name            = "standard"

  enable_rbac_authorization = true

  # Dev/teardown friendliness: purge protection off so `terraform destroy`
  # leaves nothing behind (NFR-2); soft delete (7 days) still applies.
  purge_protection_enabled   = false
  soft_delete_retention_days = 7

  public_network_access_enabled = var.public_network_access_enabled

  network_acls {
    default_action = var.public_network_access_enabled ? "Allow" : "Deny"
    # AzureServices bypass keeps the KV-backed Databricks secret scope working
    # after the FR-1.8 flip (the scope is read by the Databricks control plane).
    bypass = "AzureServices"
  }

  tags = var.tags
}

# RBAC-mode KV: even the subscription Owner needs a data-plane role to
# read/write secrets.
resource "azurerm_role_assignment" "admin" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Administrator"
  principal_id         = var.admin_object_id
}
