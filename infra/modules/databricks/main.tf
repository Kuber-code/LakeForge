# FR-1.7 — Databricks workspace: VNet injection + secure cluster connectivity
# (NPIP). Premium tier (required for Unity Catalog).
#
# Why VNet injection + NPIP (details in docs/network-design.md + ADR-0001):
# - clusters live in OUR subnets → NSGs, private endpoints and egress control apply
# - NPIP: nodes get no public IPs; control-plane traffic is relay-based outbound

resource "azurerm_databricks_workspace" "this" {
  name                = "dbw-${var.base}"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "premium"

  # Managed RG name must differ from the workspace RG; Azure locks it.
  managed_resource_group_name = "rg-${var.base}-dbx-managed"

  custom_parameters {
    no_public_ip        = true # NPIP / secure cluster connectivity
    virtual_network_id  = var.vnet_id
    public_subnet_name  = var.host_subnet_name
    private_subnet_name = var.container_subnet_name

    public_subnet_network_security_group_association_id  = var.host_nsg_association_id
    private_subnet_network_security_group_association_id = var.container_nsg_association_id
  }

  tags = var.tags
}
