# Small SQL warehouse: P1 grants verification (queries executed as different
# principals), then the P4 dashboards. Serverless by default (zero idle cost
# after auto-stop) but cannot reach private-endpoint storage without NCC; flip
# var.warehouse_serverless to false for a VNet-resident classic warehouse once
# the EDSv4 quota is raised (ADR-0008). auto_stop_mins minimum is 10.

resource "databricks_sql_endpoint" "small" {
  name                      = "wh-lakeforge"
  cluster_size              = "2X-Small"
  min_num_clusters          = 1
  max_num_clusters          = 1
  auto_stop_mins            = 10
  enable_serverless_compute = var.warehouse_serverless
  warehouse_type            = "PRO"

  depends_on = [databricks_metastore_assignment.this]
}

resource "databricks_permissions" "warehouse" {
  sql_endpoint_id = databricks_sql_endpoint.small.id

  # Group mode: the three lf_* groups. Fallback mode: the SPs directly (the
  # human engineer is the warehouse creator and already has CAN_MANAGE).
  dynamic "access_control" {
    for_each = local.groups_enabled ? {
      engineers = local.engineers_principal
      analysts  = local.analysts_principal
      jobs      = local.jobs_principal
    } : {}
    content {
      group_name       = access_control.value
      permission_level = "CAN_USE"
    }
  }

  dynamic "access_control" {
    for_each = local.groups_enabled ? {} : {
      analyst = local.analysts_principal
      deploy  = local.jobs_principal
    }
    content {
      service_principal_name = access_control.value
      permission_level       = "CAN_USE"
    }
  }

  depends_on = [
    databricks_mws_permission_assignment.groups,
    databricks_service_principal.deploy_ws,
    databricks_service_principal.analyst_ws,
  ]
}
