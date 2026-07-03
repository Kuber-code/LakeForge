# Network design (E1)

## Topology

```
VNet 10.20.0.0/22 (1024 addresses)
├── snet-dbx-host       10.20.0.0/24   delegated to Microsoft.Databricks/workspaces
├── snet-dbx-container  10.20.1.0/24   delegated to Microsoft.Databricks/workspaces
├── snet-privatelink    10.20.2.0/26   private endpoints (dfs, blob, vault)
└── (spare)             10.20.2.64+    future: SQL PE, VPN/Bastion, test subnets

NAT Gateway (natgw) ── attached to both Databricks subnets ── 1 static public IP
Private DNS zones:  privatelink.dfs.core.windows.net
                    privatelink.blob.core.windows.net
                    privatelink.vaultcore.azure.net      (all linked to the VNet)
```

/24 per Databricks subnet supports ~250 cluster nodes — far beyond this project's needs, but subnet CIDRs cannot be changed after workspace creation, so oversizing is the cheap option.

## Why VNet injection (vs managed VNet)

With the default managed VNet, Databricks compute lives in a Microsoft-managed network you cannot see or control. VNet injection places cluster NICs **in our subnets**, which is what makes everything else in this project possible:

- NSGs we own on the compute path,
- private endpoints reachable from clusters without any gateway tricks,
- a NAT gateway giving all clusters **one known egress IP** (used as a precise SQL firewall rule instead of "allow all Azure services"),
- the enterprise pattern interviewers actually run in production.

Trade-off: we own subnet sizing, NSG hygiene, and egress — accepted deliberately (ADR-0001).

## Why NPIP (secure cluster connectivity)

With `no_public_ip = true`, cluster nodes get **no public IPs at all**:

- **Inbound:** nothing on the internet can address a worker; the control plane never connects in — each cluster keeps an *outbound* tunnel to a regional relay and receives commands as replies over it.
- **Outbound:** without implicit outbound IPs, egress must be explicit — hence the NAT gateway (Azure retired implicit "default outbound access" for new subnets, so this is not optional anymore).

Result: the attack surface of the data plane is the NAT gateway's *outbound* connections only, and the NSG can stay silent about inbound control-plane rules.

## Packet paths

**Cluster → ADLS (`abfss://silver@st...dfs.core.windows.net/...`):**
1. Spark resolves `st....dfs.core.windows.net` → CNAME `st....privatelink.dfs.core.windows.net`.
2. The VNet-linked private DNS zone answers with the private endpoint's IP (`10.20.2.x`) — inside the VNet, instead of the public A record.
3. Traffic goes NIC → PE in `snet-privatelink` (never leaves the VNet), authenticated as the Access Connector MI via the UC storage credential.
4. From outside the VNet the same FQDN resolves to the public IP, where the storage firewall (`default_action = Deny` after the flip) refuses the connection.

**Cluster → Key Vault:** same CNAME/private-zone mechanics via `pe-keyvault`. Note: the **KV-backed secret scope** is read by the Databricks *control plane*, not by cluster nodes — that path uses `bypass = AzureServices` on the KV firewall and is the reason the flip keeps working with public access off.

**Cluster → Azure SQL:** public FQDN over TCP 1433, egress via the NAT gateway's static IP, which is the only non-Azure-service IP allowed through the SQL server firewall. (A SQL private endpoint is a documented future step; P1 scopes PEs to storage + KV per FR-1.8.)

**Cluster → control plane:** outbound-only 443 to the `AzureDatabricks` service tag (relay tunnel), via NAT gateway.

## What SCC + private endpoints change, concretely

| | Before (defaults) | After (LakeForge) |
|---|---|---|
| Worker public IPs | Yes | None (NPIP) |
| Control-plane → worker | Inbound connection | Outbound relay tunnel only |
| Storage/KV reachability | Public endpoints, IP-open | Private endpoints; public access **Denied** |
| Storage/KV DNS inside VNet | Public A record | Private zone → `10.20.2.x` |
| Cluster egress | Implicit, random IPs | 1 static NAT IP (pinned in SQL firewall) |

## Two-step private flip (FR-1.8)

Deploying straight to `public_network_access = false` fails: the machine running Terraform (and the seed script) is outside the VNet, and container/secret creation would be firewalled out mid-apply. So:

1. **Step 1** — `public_network_access_enabled = true` (default): full apply, seed SQL, upload a landing test file, validate that *from a cluster* `nslookup st....dfs.core.windows.net` returns `10.20.2.x` and reads succeed.
2. **Step 2** — set `public_network_access_enabled = false` in `terraform.tfvars`, `terraform apply`: storage + KV go private-only (`default_action = Deny`). Re-run the cluster read to confirm nothing broke, and confirm laptop access now fails.

Operational consequence, accepted for a portfolio project: after the flip, ad-hoc laptop access to storage/KV requires either temporarily re-enabling public access with `terraform apply`, or going through the workspace. CI in P3 uses Microsoft-hosted agents → the Terraform data-plane operations that need storage access must happen before the flip or via the `AzureServices` bypass.

## NSGs

- **Databricks subnets** (one NSG, both subnets): inbound worker-to-worker only; outbound worker-to-worker, 443→`AzureDatabricks`, 3306→`Sql` (metastore), 443→`Storage`, 9093→`EventHub`. Because the subnets are delegated, Azure's network-intent policy injects equivalent platform rules (prefixed `Microsoft.Databricks-workspaces_UseOnly_`) — ours mirror them so the posture is reviewable in code.
- **PE subnet**: inbound 443+1433 from the VNet, explicit deny-all after; PE network policies enabled so the NSG actually evaluates PE traffic.

## Cost anatomy (fixed monthly, EUR)

| Item | ~/mo |
|---|---|
| 3 private endpoints | ~21 |
| NAT gateway + IP | ~35 |
| Everything else | on-demand (clusters spot + 15-min autotermination, SQL serverless auto-pause) |

The fixed part (~56 EUR) fits the ~70 EUR (300 PLN) budget; the habit of `terraform destroy` between working sessions (NFR-2) removes even that.
