data "azurerm_client_config" "current" {}

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

module "network" {
  source = "../modules/network"

  base                = local.base
  resource_group_name = azurerm_resource_group.this.name
  location            = var.location
  address_space       = var.vnet_address_space
  subnet_cidrs        = var.subnet_cidrs
  tags                = local.tags
}
