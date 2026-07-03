# FR-1.3 — NSGs.
#
# Databricks subnets: one NSG associated to both host and container subnets,
# created EMPTY on purpose. The subnets are delegated to
# Microsoft.Databricks/workspaces, so Azure's network intent policy injects
# and owns the required rules (prefixed Microsoft.Databricks-workspaces_UseOnly_):
# worker-to-worker traffic, and outbound 443/3306/8443-8451 to the
# AzureDatabricks/Sql/Storage/EventHub service tags. Inline rules here would
# fight the policy: Terraform's authoritative security_rule block tries to
# strip the injected rules and ARM rejects the update
# (ConflictWithNetworkIntentPolicy). Hence: no inline rules + ignore_changes.
# The effective rule set is documented in docs/network-design.md.

resource "azurerm_network_security_group" "databricks" {
  name                = "nsg-dbx-${var.base}"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags

  lifecycle {
    # Rules are owned by the Databricks network intent policy.
    ignore_changes = [security_rule]
  }
}

resource "azurerm_subnet_network_security_group_association" "dbx_host" {
  subnet_id                 = azurerm_subnet.dbx_host.id
  network_security_group_id = azurerm_network_security_group.databricks.id
}

resource "azurerm_subnet_network_security_group_association" "dbx_container" {
  subnet_id                 = azurerm_subnet.dbx_container.id
  network_security_group_id = azurerm_network_security_group.databricks.id
}

# Private-endpoint subnet: restrictive — only HTTPS (storage/KV) and SQL from
# inside the VNet may reach the private endpoints; everything else denied.
# No delegation here, so these rules are fully Terraform-owned.
resource "azurerm_network_security_group" "privatelink" {
  name                = "nsg-pe-${var.base}"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags

  security_rule {
    name                       = "allow-vnet-https-inbound"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["443", "1433"]
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "VirtualNetwork"
  }

  security_rule {
    name                       = "deny-all-inbound"
    priority                   = 4000
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "privatelink" {
  subnet_id                 = azurerm_subnet.privatelink.id
  network_security_group_id = azurerm_network_security_group.privatelink.id
}
