output "key_vault_id" {
  value = azurerm_key_vault.this.id
  # Anyone consuming the vault id to write secrets must wait for the admin
  # data-plane role to exist (RBAC-mode KV).
  depends_on = [azurerm_role_assignment.admin]
}

output "key_vault_name" {
  value = azurerm_key_vault.this.name
}

output "key_vault_uri" {
  value = azurerm_key_vault.this.vault_uri
}

output "admin_role_assignment_id" {
  description = "Depend on this before writing secrets (RBAC propagation)."
  value       = azurerm_role_assignment.admin.id
}
