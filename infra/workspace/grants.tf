# FR-2.5 — grants matrix (one databricks_grants per securable: it is
# authoritative for that object). Principals come from groups.tf and are
# either account groups (target state) or service principals directly
# (MSA fallback) — the matrix itself is identical:
#
#   engineers : everything in dev, read-only prod
#   analysts  : SELECT on gold only (negative test: silver denied)
#   jobs      : everything in prod (deploy SP; owns prod pipelines from P3)

resource "databricks_grants" "catalog_dev" {
  catalog = databricks_catalog.env["dev"].name

  grant {
    principal  = local.engineers_principal
    privileges = ["ALL_PRIVILEGES"]
  }
  grant {
    principal  = local.analysts_principal
    privileges = ["USE_CATALOG"]
  }
  grant {
    principal  = local.jobs_principal
    privileges = ["USE_CATALOG", "USE_SCHEMA", "SELECT"]
  }

  depends_on = [
    databricks_schema.layer,
    databricks_mws_permission_assignment.groups,
    databricks_service_principal.deploy_ws,
    databricks_service_principal.analyst_ws,
  ]
}

resource "databricks_grants" "catalog_prod" {
  catalog = databricks_catalog.env["prod"].name

  grant {
    principal  = local.jobs_principal
    privileges = ["ALL_PRIVILEGES"]
  }
  grant {
    principal  = local.analysts_principal
    privileges = ["USE_CATALOG"]
  }
  grant {
    principal  = local.engineers_principal
    privileges = ["USE_CATALOG", "USE_SCHEMA", "SELECT"]
  }

  depends_on = [
    databricks_schema.layer,
    databricks_mws_permission_assignment.groups,
    databricks_service_principal.deploy_ws,
    databricks_service_principal.analyst_ws,
  ]
}

# Analysts: gold only. USE_CATALOG above + USE_SCHEMA/SELECT here — and
# deliberately nothing on bronze/silver/ops.
resource "databricks_grants" "gold" {
  for_each = toset(var.environments)

  schema = "${databricks_catalog.env[each.key].name}.${databricks_schema.layer["${each.key}.gold"].name}"

  grant {
    principal  = local.analysts_principal
    privileges = ["USE_SCHEMA", "SELECT"]
  }
}

# External locations: engineers may create external tables / read files in
# dev pipelines; jobs in prod (P3).
resource "databricks_grants" "external_locations" {
  for_each = databricks_external_location.layer

  external_location = each.value.id

  grant {
    principal  = local.engineers_principal
    privileges = ["READ_FILES", "WRITE_FILES", "CREATE_EXTERNAL_TABLE"]
  }
  grant {
    principal  = local.jobs_principal
    privileges = ["READ_FILES", "WRITE_FILES", "CREATE_EXTERNAL_TABLE"]
  }
}
