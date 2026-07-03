variable "prefix" {
  description = "Project prefix used in all resource names."
  type        = string
  default     = "lakeforge"
}

variable "environment" {
  description = "Environment name (dev/prod)."
  type        = string
  default     = "dev"
}

variable "location" {
  description = "Azure region."
  type        = string
  default     = "westeurope"
}

variable "vnet_address_space" {
  description = "VNet address space (FR-1.2)."
  type        = string
  default     = "10.20.0.0/22"
}

variable "subnet_cidrs" {
  description = "Subnet CIDRs inside the VNet."
  type = object({
    dbx_host      = string
    dbx_container = string
    privatelink   = string
  })
  default = {
    dbx_host      = "10.20.0.0/24"
    dbx_container = "10.20.1.0/24"
    privatelink   = "10.20.2.0/26"
  }
}

variable "public_network_access_enabled" {
  description = <<-EOT
    Two-step private-endpoint rollout (FR-1.8):
    step 1 = true  (deploy everything, validate private endpoints),
    step 2 = false (flip storage & Key Vault to private-only).
  EOT
  type        = bool
  default     = true
}

variable "budget_amount" {
  description = "Monthly budget in the subscription billing currency (EUR). 70 EUR ~ 300 PLN (FR-1.10)."
  type        = number
  default     = 70
}

variable "alert_email" {
  description = "E-mail address for budget alerts. Set in terraform.tfvars (gitignored)."
  type        = string
}

variable "devops_federation_subjects" {
  description = <<-EOT
    OIDC federated-credential subjects for the infra SP (FR-2.1), added in P3 when
    the Azure DevOps org exists. Example:
    [{ name = "azdo-lakeforge", issuer = "https://vstoken.dev.azure.com/<org-id>", subject = "sc://<org>/<project>/<service-connection>" }]
  EOT
  type = list(object({
    name    = string
    issuer  = string
    subject = string
  }))
  default = []
}

variable "tags" {
  description = "Common resource tags."
  type        = map(string)
  default = {
    project    = "lakeforge"
    managed_by = "terraform"
  }
}
