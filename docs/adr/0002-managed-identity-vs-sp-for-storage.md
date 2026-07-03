# ADR-0002: Managed identity (Access Connector) for storage, not SP + secret

**Status:** accepted (P1) · **Related:** FR-1.9, FR-2.3, docs/identity-matrix.md

## Context

Unity Catalog needs a storage credential to reach ADLS. Two options: a service
principal with a client secret, or the Databricks Access Connector's
system-assigned managed identity.

## Decision

**Access Connector MI**, holding `Storage Blob Data Contributor` on the single
lakehouse storage account. All data-plane storage access flows through it via
UC external locations; no cluster-level `fs.azure.*` OAuth configs anywhere.

## Consequences

- (+) No secret exists → nothing to leak, rotate, or expire.
- (+) Access is governed per table/volume by UC grants, not per cluster.
- (+) Every access is attributable in UC audit logs.
- (−) MI works only for Azure services that accept it; Azure SQL JDBC from
  Spark still uses KV-held credentials (see ADR-0003).
- (−) One MI for all layers: layer separation is enforced by UC grants, not by
  distinct Azure identities. Acceptable at this scale; a prod hardening step
  would be one connector per sensitivity tier.
