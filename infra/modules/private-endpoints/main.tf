# FR-1.8 — Private endpoints + private DNS for storage (dfs, blob) and Key
# Vault. Rollout is two-step (var.public_network_access_enabled on the target
# modules): deploy with public access on → validate resolution/paths → flip to
# private-only. The flip procedure is documented in docs/network-design.md.

locals {
  zones = {
    dfs   = "privatelink.dfs.core.windows.net"
    blob  = "privatelink.blob.core.windows.net"
    vault = "privatelink.vaultcore.azure.net"
  }
}

resource "azurerm_private_dns_zone" "this" {
  for_each = local.zones

  name                = each.value
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "this" {
  for_each = azurerm_private_dns_zone.this

  name                  = "link-${var.base}-${each.key}"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = each.value.name
  virtual_network_id    = var.vnet_id
  registration_enabled  = false
  tags                  = var.tags
}

locals {
  endpoints = {
    adls-dfs = {
      target_id    = var.storage_account_id
      subresource  = "dfs"
      dns_zone_key = "dfs"
    }
    adls-blob = {
      target_id    = var.storage_account_id
      subresource  = "blob"
      dns_zone_key = "blob"
    }
    keyvault = {
      target_id    = var.key_vault_id
      subresource  = "vault"
      dns_zone_key = "vault"
    }
  }
}

resource "azurerm_private_endpoint" "this" {
  for_each = local.endpoints

  name                = "pe-${each.key}-${var.base}"
  resource_group_name = var.resource_group_name
  location            = var.location
  subnet_id           = var.subnet_id

  private_service_connection {
    name                           = "psc-${each.key}"
    private_connection_resource_id = each.value.target_id
    subresource_names              = [each.value.subresource]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "dzg-${each.key}"
    private_dns_zone_ids = [azurerm_private_dns_zone.this[each.value.dns_zone_key].id]
  }

  tags = var.tags
}
