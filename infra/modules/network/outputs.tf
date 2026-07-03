output "vnet_id" {
  value = azurerm_virtual_network.this.id
}

output "vnet_name" {
  value = azurerm_virtual_network.this.name
}

output "dbx_host_subnet_name" {
  value = azurerm_subnet.dbx_host.name
}

output "dbx_container_subnet_name" {
  value = azurerm_subnet.dbx_container.name
}

output "nat_egress_ip" {
  description = "Public IP all Databricks cluster egress goes through."
  value       = azurerm_public_ip.nat.ip_address
}

output "privatelink_subnet_id" {
  value = azurerm_subnet.privatelink.id
}

output "dbx_host_nsg_association_id" {
  value = azurerm_subnet_network_security_group_association.dbx_host.id
}

output "dbx_container_nsg_association_id" {
  value = azurerm_subnet_network_security_group_association.dbx_container.id
}
