# ADR-0003: JDBC + KV secret for Azure SQL ingest, Federation documented

**Status:** accepted (P1) · **Related:** FR-2.6, FR-4.2

## Context

Bronze needs incremental extracts from Azure SQL. Candidate patterns:

1. **JDBC + SQL auth**, credentials in Key Vault, read via the KV-backed secret scope.
2. **Lakehouse Federation**: UC connection object to Azure SQL, tables queryable in place.
3. JDBC + Entra service-principal/MI token auth (no SQL logins).

## Decision

**Option 1** for the pipeline, with Federation explicitly documented as the
query-in-place alternative (this ADR satisfies FR-2.6's "document, don't build").

## Rationale & trade-offs

- The watermark pattern (FR-4.2) needs *snapshot extracts persisted to bronze*
  — replayable, auditable, decoupled from OLTP availability and auto-pause
  wakeups. Federation queries the source live: great for exploration and
  low-latency lookups, wrong as the system of record for bronze.
- Federation still needs a credential object for the connection, so it does not
  remove secret management; it moves it into UC.
- Option 3 (Entra token auth for JDBC) removes the SQL login but requires
  token-refresh plumbing in Spark and an SP secret or federation anyway;
  complexity not justified at this scale. Revisit if secrets policy tightens.
- Costs: JDBC extract wakes the serverless DB only during ingest windows;
  federated ad-hoc queries would wake it unpredictably (auto-pause defeats it).
