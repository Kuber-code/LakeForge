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

variable "sql_location" {
  description = <<-EOT
    Region for the Azure SQL server; empty = var.location. Separate because
    some credit/trial subscriptions have SQL provisioning disabled in popular
    regions (e.g. westeurope) — SQL has no private endpoint in P1 scope, so a
    neighbouring region only changes latency, not the security model.
  EOT
  type        = string
  default     = ""
}

variable "client_ip_allowlist" {
  description = "Extra IPs allowed through the SQL firewall (e.g. your workstation for seeding). Set in terraform.tfvars (gitignored)."
  type        = list(string)
  default     = []
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

# ── CI identity independence (FR-6.3) ──────────────────────────────────────
# The pipeline plans as sp-lakeforge-infra, which is not a user and cannot
# read Microsoft Graph. These pin the human-owner identity and well-known
# object ids so plans are identical regardless of who runs them. Empty
# values fall back to directory lookups (local human runs).

variable "deployer_object_id" {
  description = "Entra object id of the human platform owner (KV admin, SQL AAD admin). Empty = current identity."
  type        = string
  default     = ""
}

variable "deployer_upn" {
  description = "UPN of the human platform owner for the SQL AAD admin login. Empty = Graph lookup of the current identity."
  type        = string
  default     = ""
}

variable "azure_databricks_sp_object_id" {
  description = "Object id of the AzureDatabricks first-party app's SP in this tenant. Empty = Graph lookup."
  type        = string
  default     = ""
}
