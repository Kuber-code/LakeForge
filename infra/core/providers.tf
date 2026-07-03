# Subscription and tenant are intentionally NOT hardcoded (public repo).
# Provide them via environment variables:
#   $env:ARM_SUBSCRIPTION_ID = (az account show --query id -o tsv)
# Authentication: Azure CLI locally, OIDC (workload identity federation) in CI.
provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy    = true
      recover_soft_deleted_key_vaults = true
    }
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
}

provider "azuread" {}
