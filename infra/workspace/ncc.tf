# FR-8 / ADR-0008 — serverless Network Connectivity Config.
#
# The serverless SQL warehouse (dashboards) runs in the Databricks account
# network, so the FR-1.8 storage firewall blocks it. This NCC gives serverless
# Databricks-managed private endpoints into the lakehouse storage; once the
# connections are approved on the storage side it reaches the data over Private
# Link — no public exposure, no classic warehouse, no EDSv4 quota.
#
# Provisioned live on 2026-07-05 by scripts/setup_ncc.py (human Entra token,
# now accepted by the account API). These resources capture it as code but stay
# behind var.enable_ncc (default false) because they use the account provider —
# i.e. the infra SP must be account admin (same gate as var.enable_account_groups).
# To adopt: register the infra SP as account admin, set enable_ncc = true, and
# import the live objects (ids below), then a subsequent plan is a no-op.
#
#   NCC          fbe98cc8-e70b-43f5-9a2d-9791ac6526cc   (ncc-lakeforge-we, westeurope)
#   rule dfs     93ca93c2-4a88-4f08-abc3-e374d2c1f634
#   rule blob    0d60975f-d89c-4419-9f75-783d87f94762
#   workspace    7405607941001785  (bound to the NCC)
#
#   terraform import 'databricks_mws_network_connectivity_config.serverless[0]' \
#     '<account_id>/fbe98cc8-e70b-43f5-9a2d-9791ac6526cc'
#   terraform import 'databricks_mws_ncc_private_endpoint_rule.storage["dfs"]' \
#     '<account_id>/fbe98cc8-e70b-43f5-9a2d-9791ac6526cc/93ca93c2-4a88-4f08-abc3-e374d2c1f634'
#   terraform import 'databricks_mws_ncc_private_endpoint_rule.storage["blob"]' \
#     '<account_id>/fbe98cc8-e70b-43f5-9a2d-9791ac6526cc/0d60975f-d89c-4419-9f75-783d87f94762'
#   terraform import 'databricks_mws_ncc_binding.workspace[0]' \
#     'fbe98cc8-e70b-43f5-9a2d-9791ac6526cc/7405607941001785'

# Core exposes the storage account name + RG, not the full ARM id; build it
# from the current subscription (never hardcoded — public repo).
locals {
  storage_account_id = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${local.core.resource_group_name}/providers/Microsoft.Storage/storageAccounts/${local.core.storage_account_name}"
}

resource "databricks_mws_network_connectivity_config" "serverless" {
  count    = var.enable_ncc ? 1 : 0
  provider = databricks.account

  name   = "ncc-lakeforge-we"
  region = local.core.location
}

resource "databricks_mws_ncc_private_endpoint_rule" "storage" {
  for_each = var.enable_ncc ? toset(["dfs", "blob"]) : toset([])
  provider = databricks.account

  network_connectivity_config_id = databricks_mws_network_connectivity_config.serverless[0].network_connectivity_config_id
  resource_id                    = local.storage_account_id
  group_id                       = each.key
}

resource "databricks_mws_ncc_binding" "workspace" {
  count    = var.enable_ncc ? 1 : 0
  provider = databricks.account

  network_connectivity_config_id = databricks_mws_network_connectivity_config.serverless[0].network_connectivity_config_id
  workspace_id                   = local.core.databricks_workspace_numeric_id
}
