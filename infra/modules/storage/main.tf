# FR-1.4 — ADLS Gen2 lakehouse storage: HNS enabled, one container per
# Medallion layer, lifecycle rule cooling the landing zone after 7 days.

locals {
  containers = ["landing", "bronze", "silver", "gold", "checkpoints"]
  # st + lakeforge + dev + suffix, max 24 chars, lowercase alphanumeric only
  account_name = substr("st${replace(var.base, "-", "")}${var.suffix}", 0, 24)
}

resource "azurerm_storage_account" "this" {
  name                = local.account_name
  resource_group_name = var.resource_group_name
  location            = var.location

  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"
  is_hns_enabled           = true # ADLS Gen2

  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  public_network_access_enabled   = var.public_network_access_enabled

  # Terraform manages containers over the data plane during initial rollout;
  # end-state hardening (shared keys off) is documented in docs/network-design.md.
  shared_access_key_enabled = true

  network_rules {
    default_action = var.public_network_access_enabled ? "Allow" : "Deny"
    bypass         = ["AzureServices"]
  }

  tags = var.tags
}

resource "azurerm_storage_container" "layer" {
  for_each = toset(local.containers)

  name                  = each.key
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "private"
}

# Lifecycle: distributor drop files are consumed by Auto Loader within hours;
# after 7 days they only exist for replay/audit, so cool them down.
resource "azurerm_storage_management_policy" "lifecycle" {
  storage_account_id = azurerm_storage_account.this.id

  rule {
    name    = "landing-to-cool-after-7d"
    enabled = true

    filters {
      prefix_match = ["landing/"]
      blob_types   = ["blockBlob"]
    }

    actions {
      base_blob {
        tier_to_cool_after_days_since_modification_greater_than = 7
      }
    }
  }
}
