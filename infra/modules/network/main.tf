# FR-1.2 — VNet with Databricks host/container subnets (delegated) and a
# private-endpoint subnet.

resource "azurerm_virtual_network" "this" {
  name                = "vnet-${var.base}"
  resource_group_name = var.resource_group_name
  location            = var.location
  address_space       = [var.address_space]
  tags                = var.tags
}

# "Host" = public subnet in Databricks terms (with NPIP no public IPs are
# actually attached; the name refers to the workspace wiring, see docs/network-design.md).
resource "azurerm_subnet" "dbx_host" {
  name                 = "snet-dbx-host"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [var.subnet_cidrs.dbx_host]

  delegation {
    name = "databricks"
    service_delegation {
      name = "Microsoft.Databricks/workspaces"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action",
        "Microsoft.Network/virtualNetworks/subnets/prepareNetworkPolicies/action",
        "Microsoft.Network/virtualNetworks/subnets/unprepareNetworkPolicies/action",
      ]
    }
  }
}

resource "azurerm_subnet" "dbx_container" {
  name                 = "snet-dbx-container"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [var.subnet_cidrs.dbx_container]

  delegation {
    name = "databricks"
    service_delegation {
      name = "Microsoft.Databricks/workspaces"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action",
        "Microsoft.Network/virtualNetworks/subnets/prepareNetworkPolicies/action",
        "Microsoft.Network/virtualNetworks/subnets/unprepareNetworkPolicies/action",
      ]
    }
  }
}

resource "azurerm_subnet" "privatelink" {
  name                              = "snet-privatelink"
  resource_group_name               = var.resource_group_name
  virtual_network_name              = azurerm_virtual_network.this.name
  address_prefixes                  = [var.subnet_cidrs.privatelink]
  private_endpoint_network_policies = "Enabled" # let the NSG apply to PE traffic
}

# Explicit egress for the Databricks subnets. Azure retired implicit "default
# outbound access" for new subnets — without a NAT gateway, NPIP cluster nodes
# cannot reach the Databricks control plane and never start.
resource "azurerm_public_ip" "nat" {
  name                = "pip-nat-${var.base}"
  resource_group_name = var.resource_group_name
  location            = var.location
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = var.tags
}

resource "azurerm_nat_gateway" "this" {
  name                    = "natgw-${var.base}"
  resource_group_name     = var.resource_group_name
  location                = var.location
  sku_name                = "Standard"
  idle_timeout_in_minutes = 4
  tags                    = var.tags
}

resource "azurerm_nat_gateway_public_ip_association" "this" {
  nat_gateway_id       = azurerm_nat_gateway.this.id
  public_ip_address_id = azurerm_public_ip.nat.id
}

resource "azurerm_subnet_nat_gateway_association" "dbx_host" {
  subnet_id      = azurerm_subnet.dbx_host.id
  nat_gateway_id = azurerm_nat_gateway.this.id
}

resource "azurerm_subnet_nat_gateway_association" "dbx_container" {
  subnet_id      = azurerm_subnet.dbx_container.id
  nat_gateway_id = azurerm_nat_gateway.this.id
}
