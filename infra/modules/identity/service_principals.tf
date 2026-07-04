# E2 — Service principals with deliberately distinct blast radii.
# Full who/what/why table: docs/identity-matrix.md.

# ── FR-2.1: sp-lakeforge-infra ─────────────────────────────────────────────
# Used by Azure DevOps to run Terraform. Contributor on the project RG (not
# the subscription) + User Access Administrator so Terraform can create role
# assignments (constrained to the data-plane roles this project uses).
# Authenticates via OIDC workload identity federation — it has NO client secret.

resource "azuread_application" "infra" {
  display_name = "sp-${var.base}-infra"
  notes        = "LakeForge: Terraform CI/CD identity (OIDC only, no secrets). FR-2.1"
}

resource "azuread_service_principal" "infra" {
  client_id = azuread_application.infra.client_id
}

resource "azurerm_role_assignment" "infra_contributor" {
  scope                = var.resource_group_id
  role_definition_name = "Contributor"
  principal_id         = azuread_service_principal.infra.object_id
}

resource "azurerm_role_assignment" "infra_uaa" {
  scope                = var.resource_group_id
  role_definition_name = "User Access Administrator"
  principal_id         = azuread_service_principal.infra.object_id

  # Limit which roles the SP may grant: only the data-plane roles used here.
  condition_version = "2.0"
  condition         = <<-EOT
    (
      (!(ActionMatches{'Microsoft.Authorization/roleAssignments/write'}))
      OR
      (@Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {ba92f5b4-2d11-453d-a403-e96b0029c9fe, 4633458b-17de-408a-b874-0445c86b69e6, b86a8fe4-44ce-4948-aee5-eccb2c155cd7}
      )
    )
    AND
    (
      (!(ActionMatches{'Microsoft.Authorization/roleAssignments/delete'}))
      OR
      (@Resource[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {ba92f5b4-2d11-453d-a403-e96b0029c9fe, 4633458b-17de-408a-b874-0445c86b69e6, b86a8fe4-44ce-4948-aee5-eccb2c155cd7}
      )
    )
  EOT
  # ba92f5b4: Storage Blob Data Contributor, 4633458b: Key Vault Secrets User,
  # b86a8fe4: Key Vault Secrets Officer
}

# Access to the Terraform state storage account lives in a different RG.
data "azurerm_resource_group" "tfstate" {
  name = var.tfstate_resource_group_name
}

resource "azurerm_role_assignment" "infra_tfstate" {
  scope                = data.azurerm_resource_group.tfstate.id
  role_definition_name = "Contributor"
  principal_id         = azuread_service_principal.infra.object_id
}

# Account-plane exception: the Databricks ACCOUNT console REST API rejects
# personal Microsoft accounts (MSA), so local Terraform runs cannot use the
# human's azure-cli auth for account-level objects (UC groups, workspace
# assignments). The infra SP is registered as a Databricks account admin and
# authenticates with this Entra client secret — stored only in Key Vault,
# 90-day rotation. Azure DevOps pipelines (P3) still use OIDC only.
resource "time_rotating" "infra_secret" {
  rotation_days = 90
}

resource "azuread_application_password" "infra_account_plane" {
  application_id = azuread_application.infra.id
  display_name   = "databricks-account-plane"
  rotate_when_changed = {
    rotation = time_rotating.infra_secret.id
  }
}

resource "azurerm_key_vault_secret" "infra_client_secret" {
  name         = "sp-infra-client-secret"
  value        = azuread_application_password.infra_account_plane.value
  key_vault_id = var.key_vault_id
  content_type = "text/plain"
}

# OIDC federated credentials (no client secrets — NFR-1). Subjects arrive in
# P3 with the Azure DevOps service connection; empty list until then.
resource "azuread_application_federated_identity_credential" "infra" {
  for_each = { for s in var.devops_federation_subjects : s.name => s }

  application_id = azuread_application.infra.id
  display_name   = each.value.name
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = each.value.issuer
  subject        = each.value.subject
}

# ── FR-2.2: sp-lakeforge-deploy ────────────────────────────────────────────
# Added to the Databricks workspace (infra/workspace stack) for
# `databricks bundle deploy` and as run-as of prod jobs. It needs NO Azure
# RBAC roles — its permissions live entirely inside Databricks/Unity Catalog.

resource "azuread_application" "deploy" {
  display_name = "sp-${var.base}-deploy"
  notes        = "LakeForge: DAB deploy + prod jobs run-as identity. FR-2.2"
}

resource "azuread_service_principal" "deploy" {
  client_id = azuread_application.deploy.client_id
}

resource "azuread_application_federated_identity_credential" "deploy" {
  for_each = { for s in var.devops_federation_subjects : "deploy-${s.name}" => s }

  application_id = azuread_application.deploy.id
  display_name   = each.value.name
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = each.value.issuer
  subject        = each.value.subject
}

# The one Azure role this SP holds: Reader on the RG, and only because the
# Azure DevOps AzureCLI task must run `az account set` after the federated
# login — a subscription is invisible to a principal with no role in it.
# Reader cannot read Key Vault secrets or modify anything (P3, FR-6.5).
resource "azurerm_role_assignment" "deploy_reader" {
  scope                = var.resource_group_id
  role_definition_name = "Reader"
  principal_id         = azuread_service_principal.deploy.object_id
}

# ── FR-2.5 (negative test): sp-lakeforge-analyst ───────────────────────────
# Member of lf_analysts (SELECT on gold only). Exists to prove the grants
# matrix by *failing* to read silver. Client secret is unavoidable here (it
# must log in to Databricks non-interactively without federation); it is
# generated by Terraform, stored only in Key Vault, rotated by re-apply.

resource "azuread_application" "analyst" {
  display_name = "sp-${var.base}-analyst"
  notes        = "LakeForge: analyst test identity for UC grants negative tests. FR-2.5"
}

resource "azuread_service_principal" "analyst" {
  client_id = azuread_application.analyst.client_id
}

resource "time_rotating" "analyst_secret" {
  rotation_days = 90
}

resource "azuread_application_password" "analyst" {
  application_id = azuread_application.analyst.id
  display_name   = "uc-negative-test"
  rotate_when_changed = {
    rotation = time_rotating.analyst_secret.id
  }
}

resource "azurerm_key_vault_secret" "analyst_client_secret" {
  name         = "sp-analyst-client-secret"
  value        = azuread_application_password.analyst.value
  key_vault_id = var.key_vault_id
  content_type = "text/plain"
}

resource "azurerm_key_vault_secret" "analyst_client_id" {
  name         = "sp-analyst-client-id"
  value        = azuread_application.analyst.client_id
  key_vault_id = var.key_vault_id
  content_type = "text/plain"
}
