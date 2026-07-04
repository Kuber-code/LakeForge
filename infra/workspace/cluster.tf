# Small single-node UC cluster used for P1 verification (reading ADLS through
# the Access Connector) and interactive exploration. Spot with fallback,
# 15-minute autotermination (NFR-2).

data "databricks_spark_version" "lts" {
  long_term_support = true

  depends_on = [databricks_metastore_assignment.this]
}

data "databricks_node_type" "smallest" {
  local_disk = true
  category   = "General Purpose"

  depends_on = [databricks_metastore_assignment.this]
}

resource "databricks_cluster" "smoke" {
  cluster_name            = "lakeforge-smoke"
  spark_version           = data.databricks_spark_version.lts.id
  node_type_id            = data.databricks_node_type.smallest.id
  autotermination_minutes = 15
  num_workers             = 0

  spark_conf = {
    "spark.databricks.cluster.profile" = "singleNode"
    "spark.master"                     = "local[*]"
  }

  custom_tags = {
    ResourceClass = "SingleNode"
    project       = "lakeforge"
  }

  data_security_mode = "SINGLE_USER"
  single_user_name   = local.engineer_user_name

  azure_attributes {
    availability       = "SPOT_WITH_FALLBACK_AZURE"
    first_on_demand    = 1
    spot_bid_max_price = -1
  }
}
