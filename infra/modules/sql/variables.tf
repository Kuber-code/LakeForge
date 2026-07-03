variable "base" {
  type = string
}

variable "suffix" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "aad_admin_object_id" {
  description = "Object id of the Entra ID admin of the SQL server (the platform owner)."
  type        = string
}

variable "aad_admin_login" {
  description = "Display login of the Entra ID admin (UPN)."
  type        = string
}

variable "key_vault_id" {
  description = "Vault receiving the SQL credentials (FR-2.4)."
  type        = string
}

variable "databricks_egress_ip" {
  description = "Public IP of the Databricks subnets' NAT gateway — the only cluster egress address; allowed through the SQL firewall."
  type        = string
}

variable "client_ip_allowlist" {
  description = "Optional extra IPs (e.g. your workstation for seeding). Set in terraform.tfvars (gitignored)."
  type        = list(string)
  default     = []
}

variable "tags" {
  type    = map(string)
  default = {}
}
