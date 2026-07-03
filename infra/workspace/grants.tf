# FR-2.5 — grants matrix (one databricks_grants per securable: it is
# authoritative for that object).
#
#   lf_engineers : everything in dev
#   lf_analysts  : SELECT on gold only (negative test: silver denied)
#   lf_jobs      : everything in prod (deploy SP; owns prod pipelines from P3)

resource "databricks_grants" "catalog_dev" {
  catalog = databricks_catalog.env["dev"].name

  grant {
    principal  = databricks_group.engineers.display_name
    privileges = ["ALL_PRIVILEGES"]
  }
  grant {
    principal  = databricks_group.analysts.display_name
    privileges = ["USE_CATALOG"]
  }
  grant {
    principal  = databricks_group.jobs.display_name
    privileges = ["USE_CATALOG", "USE_SCHEMA", "SELECT"]
  }

  depends_on = [databricks_mws_permission_assignment.groups]
}

resource "databricks_grants" "catalog_prod" {
  catalog = databricks_catalog.env["prod"].name

  grant {
    principal  = databricks_group.jobs.display_name
    privileges = ["ALL_PRIVILEGES"]
  }
  grant {
    principal  = databricks_group.analysts.display_name
    privileges = ["USE_CATALOG"]
  }
  grant {
    principal  = databricks_group.engineers.display_name
    privileges = ["USE_CATALOG", "USE_SCHEMA", "SELECT"]
  }

  depends_on = [databricks_mws_permission_assignment.groups]
}

# Analysts: gold only. USE_CATALOG above + USE_SCHEMA/SELECT here — and
# deliberately nothing on bronze/silver/ops.
resource "databricks_grants" "gold" {
  for_each = toset(var.environments)

  schema = "${databricks_catalog.env[each.key].name}.${databricks_schema.layer["${each.key}.gold"].name}"

  grant {
    principal  = databricks_group.analysts.display_name
    privileges = ["USE_SCHEMA", "SELECT"]
  }

  depends_on = [databricks_mws_permission_assignment.groups]
}

# External locations: engineers may create external tables / read files in
# dev pipelines; jobs in prod (P3).
resource "databricks_grants" "external_locations" {
  for_each = databricks_external_location.layer

  external_location = each.value.id

  grant {
    principal  = databricks_group.engineers.display_name
    privileges = ["READ_FILES", "WRITE_FILES", "CREATE_EXTERNAL_TABLE"]
  }
  grant {
    principal  = databricks_group.jobs.display_name
    privileges = ["READ_FILES", "WRITE_FILES", "CREATE_EXTERNAL_TABLE"]
  }

  depends_on = [databricks_mws_permission_assignment.groups]
}
