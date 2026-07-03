# Small serverless SQL warehouse: used by the P1 grants verification (queries
# executed as different principals), later by dashboards (P4). Serverless →
# zero idle cost after auto-stop.

resource "databricks_sql_endpoint" "small" {
  name                      = "wh-lakeforge"
  cluster_size              = "2X-Small"
  min_num_clusters          = 1
  max_num_clusters          = 1
  auto_stop_mins            = 5
  enable_serverless_compute = true
  warehouse_type            = "PRO"

  depends_on = [databricks_metastore_assignment.this]
}

resource "databricks_permissions" "warehouse" {
  sql_endpoint_id = databricks_sql_endpoint.small.id

  access_control {
    group_name       = databricks_group.engineers.display_name
    permission_level = "CAN_USE"
  }
  access_control {
    group_name       = databricks_group.analysts.display_name
    permission_level = "CAN_USE"
  }
  access_control {
    group_name       = databricks_group.jobs.display_name
    permission_level = "CAN_USE"
  }

  depends_on = [databricks_mws_permission_assignment.groups]
}
