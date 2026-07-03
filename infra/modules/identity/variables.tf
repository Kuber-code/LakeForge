variable "base" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "resource_group_id" {
  type = string
}

variable "location" {
  type = string
}

variable "storage_account_id" {
  type = string
}

variable "key_vault_id" {
  type = string
}

variable "tfstate_resource_group_name" {
  description = "Resource group holding the Terraform state storage account (infra SP needs it)."
  type        = string
  default     = "rg-lakeforge-tfstate"
}

variable "devops_federation_subjects" {
  description = "OIDC federated credentials for the infra SP (populated in P3 when the Azure DevOps org exists)."
  type = list(object({
    name    = string
    issuer  = string
    subject = string
  }))
  default = []
}

variable "tags" {
  type    = map(string)
  default = {}
}
