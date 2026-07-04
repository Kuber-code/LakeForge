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

variable "tenant_id" {
  type = string
}

variable "admin_object_id" {
  description = "Object id granted Key Vault Administrator (the human platform owner)."
  type        = string
}

variable "public_network_access_enabled" {
  description = "FR-1.8 two-step flip: true until private endpoints are validated."
  type        = bool
  default     = true
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "azure_databricks_sp_object_id" {
  description = "Pinned object id of the AzureDatabricks first-party SP; empty = Graph lookup (needs directory read rights)."
  type        = string
  default     = ""
}
