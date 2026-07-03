# FR-1.6 — Azure SQL Server + serverless database: the OLTP source system
# (brewery sales & distribution). Auto-pauses after 60 minutes (NFR-2).

resource "random_password" "sql_admin" {
  length           = 24
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?" # avoid chars that break JDBC URLs (@ ; /)
  min_lower        = 1
  min_upper        = 1
  min_numeric      = 1
  min_special      = 1
}

resource "azurerm_mssql_server" "this" {
  name                = "sql-${var.base}-${var.suffix}"
  resource_group_name = var.resource_group_name
  location            = var.location
  version             = "12.0"

  # SQL auth kept enabled: the Databricks JDBC ingest (FR-4.2) authenticates
  # with credentials read from Key Vault. The Entra-only alternative is
  # documented in docs/adr (FR-2.6).
  administrator_login          = "lakeforge_admin"
  administrator_login_password = random_password.sql_admin.result

  azuread_administrator {
    login_username = var.aad_admin_login
    object_id      = var.aad_admin_object_id
  }

  minimum_tls_version           = "1.2"
  public_network_access_enabled = true # no private endpoint in scope for SQL (FR-1.8 covers storage/KV)

  tags = var.tags
}

resource "azurerm_mssql_database" "oltp" {
  name      = "sqldb-brewery-oltp"
  server_id = azurerm_mssql_server.this.id

  # Serverless: GP_S_Gen5_1, auto-pause after 60 min
  sku_name                    = "GP_S_Gen5_1"
  min_capacity                = 0.5
  auto_pause_delay_in_minutes = 60
  max_size_gb                 = 4
  zone_redundant              = false
  storage_account_type        = "Local"

  tags = var.tags
}

# Databricks clusters egress through the NAT gateway, so this single IP is
# the precise allow rule (instead of the broad "allow Azure services" 0.0.0.0).
resource "azurerm_mssql_firewall_rule" "databricks_nat" {
  name             = "allow-databricks-nat-egress"
  server_id        = azurerm_mssql_server.this.id
  start_ip_address = var.databricks_egress_ip
  end_ip_address   = var.databricks_egress_ip
}

resource "azurerm_mssql_firewall_rule" "client" {
  for_each = toset(var.client_ip_allowlist)

  name             = "allow-client-${replace(each.value, ".", "-")}"
  server_id        = azurerm_mssql_server.this.id
  start_ip_address = each.value
  end_ip_address   = each.value
}

# FR-2.4 — SQL connection credentials in Key Vault; Databricks reads them via
# the KV-backed secret scope. No secret value ever lands in code or state
# outputs (random_password lives in remote state, which is private and
# access-controlled — see docs/identity-matrix.md).
resource "azurerm_key_vault_secret" "sql_user" {
  name         = "sql-admin-login"
  value        = azurerm_mssql_server.this.administrator_login
  key_vault_id = var.key_vault_id
  content_type = "text/plain"
}

resource "azurerm_key_vault_secret" "sql_password" {
  name         = "sql-admin-password"
  value        = random_password.sql_admin.result
  key_vault_id = var.key_vault_id
  content_type = "text/plain"
}

resource "azurerm_key_vault_secret" "sql_jdbc_url" {
  name         = "sql-jdbc-url"
  value        = "jdbc:sqlserver://${azurerm_mssql_server.this.fully_qualified_domain_name}:1433;database=${azurerm_mssql_database.oltp.name};encrypt=true;trustServerCertificate=false;loginTimeout=30"
  key_vault_id = var.key_vault_id
  content_type = "text/plain"
}
