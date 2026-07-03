data "azurerm_client_config" "current" {}

# UPN of the deploying human — becomes the Entra admin of the SQL server.
data "azuread_user" "deployer" {
  object_id = data.azurerm_client_config.current.object_id
}

locals {
  base = "${var.prefix}-${var.environment}" # e.g. lakeforge-dev
  tags = merge(var.tags, { environment = var.environment })
}

# Deterministic-per-state random suffix for globally-unique names (storage, KV, SQL).
resource "random_string" "suffix" {
  length  = 6
  lower   = true
  numeric = true
  upper   = false
  special = false
}

resource "azurerm_resource_group" "this" {
  name     = "rg-${local.base}"
  location = var.location
  tags     = local.tags
}

module "storage" {
  source = "../modules/storage"

  base                          = local.base
  suffix                        = random_string.suffix.result
  resource_group_name           = azurerm_resource_group.this.name
  location                      = var.location
  public_network_access_enabled = var.public_network_access_enabled
  tags                          = local.tags
}

module "keyvault" {
  source = "../modules/keyvault"

  base                          = local.base
  suffix                        = random_string.suffix.result
  resource_group_name           = azurerm_resource_group.this.name
  location                      = var.location
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  admin_object_id               = data.azurerm_client_config.current.object_id
  public_network_access_enabled = var.public_network_access_enabled
  tags                          = local.tags
}

module "sql" {
  source = "../modules/sql"

  base                 = local.base
  suffix               = random_string.suffix.result
  resource_group_name  = azurerm_resource_group.this.name
  location             = var.sql_location != "" ? var.sql_location : var.location
  aad_admin_object_id  = data.azurerm_client_config.current.object_id
  aad_admin_login      = data.azuread_user.deployer.user_principal_name
  key_vault_id         = module.keyvault.key_vault_id
  databricks_egress_ip = module.network.nat_egress_ip
  client_ip_allowlist  = var.client_ip_allowlist
  tags                 = local.tags
}

module "network" {
  source = "../modules/network"

  base                = local.base
  resource_group_name = azurerm_resource_group.this.name
  location            = var.location
  address_space       = var.vnet_address_space
  subnet_cidrs        = var.subnet_cidrs
  tags                = local.tags
}

module "private_endpoints" {
  source = "../modules/private-endpoints"

  base                = local.base
  resource_group_name = azurerm_resource_group.this.name
  location            = var.location
  vnet_id             = module.network.vnet_id
  subnet_id           = module.network.privatelink_subnet_id
  storage_account_id  = module.storage.storage_account_id
  key_vault_id        = module.keyvault.key_vault_id
  tags                = local.tags
}

module "identity" {
  source = "../modules/identity"

  base                       = local.base
  resource_group_name        = azurerm_resource_group.this.name
  resource_group_id          = azurerm_resource_group.this.id
  location                   = var.location
  storage_account_id         = module.storage.storage_account_id
  key_vault_id               = module.keyvault.key_vault_id
  devops_federation_subjects = var.devops_federation_subjects
  tags                       = local.tags
}

module "databricks" {
  source = "../modules/databricks"

  base                         = local.base
  resource_group_name          = azurerm_resource_group.this.name
  location                     = var.location
  vnet_id                      = module.network.vnet_id
  host_subnet_name             = module.network.dbx_host_subnet_name
  container_subnet_name        = module.network.dbx_container_subnet_name
  host_nsg_association_id      = module.network.dbx_host_nsg_association_id
  container_nsg_association_id = module.network.dbx_container_nsg_association_id
  tags                         = local.tags
}
