# ADR-0001: VNet injection + NPIP instead of the managed default VNet

**Status:** accepted (P1) · **Related:** FR-1.7, docs/network-design.md

## Context

Azure Databricks deploys by default into a Microsoft-managed VNet: zero network
configuration, but no NSG control, no private-endpoint reachability guarantees,
no controlled egress IP, and public IPs on workers unless SCC is enabled.

## Decision

Deploy the workspace with **VNet injection** into our own delegated subnets and
**secure cluster connectivity (NPIP)**, plus a NAT gateway for explicit egress.

## Consequences

- (+) Clusters can reach storage/KV over **private endpoints**; public access on
  those services can be disabled entirely (FR-1.8, NFR-1).
- (+) One static egress IP → precise SQL firewall rule instead of allow-all-Azure.
- (+) NSGs, DNS and packet paths are ours to demonstrate — the point of the project.
- (−) We own subnet sizing (fixed at workspace creation), NSG rules, NAT cost
  (~35 EUR/mo, the single biggest fixed cost).
- (−) Slightly slower cluster start (relay tunnel setup) — irrelevant here.
