# E3 — metastore wiring. Azure normally auto-provisions a regional metastore
# and assigns new workspaces to it; the variables cover the other cases
# (see variables.tf) so the stack works on any account.

resource "databricks_metastore" "this" {
  count    = var.create_metastore ? 1 : 0
  provider = databricks.account

  name          = "metastore-${local.core.location}"
  region        = local.core.location
  force_destroy = true
}

locals {
  metastore_id = var.create_metastore ? databricks_metastore.this[0].id : var.metastore_id
}

resource "databricks_metastore_assignment" "this" {
  count    = local.metastore_id != "" ? 1 : 0
  provider = databricks.account

  workspace_id = local.core.databricks_workspace_numeric_id
  metastore_id = local.metastore_id
}
