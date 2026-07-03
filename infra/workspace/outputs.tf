output "catalogs" {
  value = [for c in databricks_catalog.env : c.name]
}

output "secret_scope" {
  value = databricks_secret_scope.kv.name
}

output "smoke_cluster_id" {
  value = databricks_cluster.smoke.id
}

output "sql_warehouse_id" {
  value = databricks_sql_endpoint.small.id
}

output "landing_volume_dev" {
  value = "/Volumes/${databricks_catalog.env["dev"].name}/bronze/${databricks_volume.landing["dev"].name}"
}
