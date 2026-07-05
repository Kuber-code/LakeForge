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

variable "enable_account_groups" {
  description = <<-EOT
    FR-2.5 target state: account-level groups (lf_engineers/lf_analysts/lf_jobs)
    managed by Terraform through the account provider. Requires a principal
    with the Databricks *account admin* role.

    Set to false when no account-admin credential is available (e.g. personal
    Microsoft accounts are rejected by the account REST API and the console
    registration of the infra SP is not done yet): service principals are then
    registered through the workspace SCIM API and UC grants target the SPs
    directly. Flip to true and re-apply once account access exists — the
    grants matrix converges to the group model.
  EOT
  type        = bool
  default     = true
}

variable "environments" {
  description = "Catalog environments (FR-3.1)."
  type        = list(string)
  default     = ["dev", "prod"]
}

variable "engineer_user_name" {
  description = "Workspace user name of the human engineer (cluster single-user, fallback grants). Empty = current identity lookup; pinned in CI where the infra SP plans."
  type        = string
  default     = ""
}

variable "warehouse_serverless" {
  description = <<-EOT
    Dashboard SQL warehouse compute model (FR-8, ADR-0008).

    true  (default): serverless — zero idle cost, but runs in the Databricks
      account network and CANNOT reach the private-endpoint storage until NCC
      private endpoints are configured (needs account-console access). Fine for
      system.* tables; the gold/ops dashboards stay dark.
    false: classic (PRO) — runs in the customer VNet like the job clusters, so
      it reaches private storage and the dashboards render. A 2X-Small needs
      **16 vCPU in the westeurope standardEDSv4Family** (measured: 2× E8ds_v4);
      raise that quota via a portal ticket before flipping this to false.
  EOT
  type        = bool
  default     = true
}
