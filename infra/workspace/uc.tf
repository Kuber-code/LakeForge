# E3 — Unity Catalog objects: storage credential (managed identity), external
# locations per container, catalogs/schemas per environment, landing volumes.

locals {
  sa         = local.core.storage_account_name
  containers = ["landing", "bronze", "silver", "gold", "checkpoints"]
  abfss      = { for c in local.containers : c => "abfss://${c}@${local.sa}.dfs.core.windows.net" }
}

# FR-2.3 — the Access Connector's managed identity as the UC storage
# credential: tokens are issued at runtime, nothing to rotate or leak.
resource "databricks_storage_credential" "mi" {
  name    = "cred-lakeforge-mi"
  comment = "Access Connector system-assigned MI (FR-1.9/FR-2.3)"

  azure_managed_identity {
    access_connector_id = local.core.access_connector_id
  }

  depends_on = [databricks_metastore_assignment.this]
}

resource "databricks_external_location" "layer" {
  for_each = toset(local.containers)

  name            = "loc-${each.key}"
  url             = "${local.abfss[each.key]}/"
  credential_name = databricks_storage_credential.mi.name
  comment         = "Lakehouse container '${each.key}' (FR-3.2)"
}

# FR-3.1 — catalogs per environment with bronze/silver/gold/ops schemas.
# Managed tables everywhere (ADR-0004); per-layer containers are preserved by
# giving every schema a managed location inside its layer's container.
resource "databricks_catalog" "env" {
  for_each = toset(var.environments)

  name          = "lakeforge_${each.key}"
  comment       = "LakeForge ${each.key} lakehouse catalog"
  storage_root  = "${local.abfss["checkpoints"]}/uc/${each.key}"
  force_destroy = true

  properties = {
    environment = each.key
  }

  depends_on = [databricks_external_location.layer]
}

locals {
  # schema -> container hosting its managed data
  schema_container = {
    bronze = "bronze"
    silver = "silver"
    gold   = "gold"
    ops    = "checkpoints"
  }
  schemas = {
    for pair in setproduct(var.environments, keys(local.schema_container)) :
    "${pair[0]}.${pair[1]}" => { env = pair[0], schema = pair[1] }
  }
}

resource "databricks_schema" "layer" {
  for_each = local.schemas

  catalog_name  = databricks_catalog.env[each.value.env].name
  name          = each.value.schema
  comment       = "${each.value.schema} layer (${each.value.env})"
  storage_root  = "${local.abfss[local.schema_container[each.value.schema]]}/${each.value.env}/managed/${each.value.schema}"
  force_destroy = true

  properties = {
    layer = each.value.schema
    owner = "lakeforge"
    pii   = "false"
  }
}

# FR-3.3 — external volume over the landing container; Auto Loader (P2) reads
# distributor drops from here.
resource "databricks_volume" "landing" {
  for_each = toset(var.environments)

  name             = "landing"
  catalog_name     = databricks_catalog.env[each.key].name
  schema_name      = databricks_schema.layer["${each.key}.bronze"].name
  volume_type      = "EXTERNAL"
  storage_location = "${local.abfss["landing"]}/${each.key}"
  comment          = "Distributor CSV/JSON drop zone (FR-3.3)"
}
