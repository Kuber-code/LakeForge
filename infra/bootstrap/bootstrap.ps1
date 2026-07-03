<#
.SYNOPSIS
    One-time bootstrap of the Terraform remote-state storage account (FR-1.1).

.DESCRIPTION
    Creates a dedicated resource group + storage account + blob container for
    Terraform state, then writes infra/backend.hcl (gitignored) with the partial
    backend config used by `terraform init -backend-config`.

    Idempotent: safe to re-run. Requires an authenticated Azure CLI session.

.EXAMPLE
    ./bootstrap.ps1
    ./bootstrap.ps1 -Location polandcentral
#>
[CmdletBinding()]
param(
    [string]$Location = "westeurope",
    [string]$ResourceGroup = "rg-lakeforge-tfstate",
    [string]$ContainerName = "tfstate"
)

$ErrorActionPreference = "Stop"

$subscriptionId = az account show --query id -o tsv
if (-not $subscriptionId) { throw "Not logged in to Azure CLI. Run 'az login' first." }

# Deterministic globally-unique SA name that does not embed the subscription id
$hash = [System.BitConverter]::ToString(
    [System.Security.Cryptography.SHA256]::Create().ComputeHash(
        [System.Text.Encoding]::UTF8.GetBytes($subscriptionId))
).Replace("-", "").Substring(0, 8).ToLower()
$storageAccount = "stlakeforgetf$hash"

Write-Host "Subscription : $subscriptionId"
Write-Host "State SA     : $storageAccount ($Location)"

az group create --name $ResourceGroup --location $Location --output none

az storage account create `
    --name $storageAccount `
    --resource-group $ResourceGroup `
    --location $Location `
    --sku Standard_LRS `
    --kind StorageV2 `
    --min-tls-version TLS1_2 `
    --allow-blob-public-access false `
    --output none

# Blob versioning: recover from accidental state corruption
az storage account blob-service-properties update `
    --account-name $storageAccount `
    --resource-group $ResourceGroup `
    --enable-versioning true `
    --output none

az storage container create `
    --name $ContainerName `
    --account-name $storageAccount `
    --auth-mode key `
    --output none

$backendHcl = @"
resource_group_name  = "$ResourceGroup"
storage_account_name = "$storageAccount"
container_name       = "$ContainerName"
"@
$backendPath = Join-Path $PSScriptRoot "..\backend.hcl"
Set-Content -Path $backendPath -Value $backendHcl -Encoding utf8

# The workspace stack reads core outputs via terraform_remote_state, which
# cannot use partial backend config — generate its tfvars too (gitignored).
$stateVars = @"
state_resource_group_name  = "$ResourceGroup"
state_storage_account_name = "$storageAccount"
state_container_name       = "$ContainerName"
"@
Set-Content -Path (Join-Path $PSScriptRoot "..\workspace\remote-state.auto.tfvars") -Value $stateVars -Encoding utf8

Write-Host "Backend config written to infra/backend.hcl and infra/workspace/remote-state.auto.tfvars (both gitignored)."
Write-Host "Next: cd infra/core; terraform init -backend-config=`"../backend.hcl`""
