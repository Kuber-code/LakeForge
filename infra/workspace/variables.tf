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

variable "enable_ncc" {
  description = <<-EOT
    FR-8 / ADR-0008: manage the serverless Network Connectivity Config (NCC +
    private-endpoint rules into the lakehouse storage + workspace binding) in
    Terraform. Requires the account provider — i.e. the infra SP registered as
    account admin (same gate as var.enable_account_groups).

    Left false while the NCC is provisioned out-of-band by scripts/setup_ncc.py
    (human Entra token, now accepted by the account API). Flip to true and
    import the existing objects once the infra SP has account admin; live ids
    are in ncc.tf for the import.
  EOT
  type        = bool
  default     = false
}

variable "warehouse_serverless" {
  description = <<-EOT
    Dashboard SQL warehouse compute model (FR-8, ADR-0008).

    true  (default): serverless — zero idle cost. It runs in the Databricks
      account network, so it reaches the private-endpoint storage via the NCC
      (see var.enable_ncc / ncc.tf); with the NCC in place the gold/ops
      dashboards render. Without an NCC it can still read system.* tables only.
    false: classic (PRO) — runs in the customer VNet like the job clusters and
      reaches private storage directly, but a 2X-Small needs **16 vCPU in the
      westeurope standardEDSv4Family** (measured: 2× E8ds_v4) and that quota
      ticket was rejected. Kept as a documented fallback; NCC is the path taken.
  EOT
  type        = bool
  default     = true
}
