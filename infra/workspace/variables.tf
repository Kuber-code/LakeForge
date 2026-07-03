variable "databricks_account_id" {
  description = "Databricks account id (account console → user menu). Not a secret, but kept in tfvars (gitignored) — public repo hygiene."
  type        = string
}

variable "state_resource_group_name" {
  description = "Terraform state RG (written to remote-state.auto.tfvars by bootstrap.ps1)."
  type        = string
}

variable "state_storage_account_name" {
  type = string
}

variable "state_container_name" {
  type    = string
  default = "tfstate"
}

variable "metastore_id" {
  description = <<-EOT
    Unity Catalog metastore id for the region.
    - ""              : metastore already auto-assigned to the workspace (Azure default) — do nothing
    - "<uuid>"        : existing metastore to assign the workspace to
    - use var.create_metastore when the account has no metastore in the region yet
  EOT
  type        = string
  default     = ""
}

variable "create_metastore" {
  description = "Create a new regional metastore (only when none exists in the account)."
  type        = bool
  default     = false
}

variable "environments" {
  description = "Catalog environments (FR-3.1)."
  type        = list(string)
  default     = ["dev", "prod"]
}
