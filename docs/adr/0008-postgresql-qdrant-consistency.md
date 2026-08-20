# ADR 0008: PostgreSQL/Qdrant cross-store consistency model

- Status: Accepted
- Date: 2026-08-20

## Context

PostgreSQL owns legal master data while Qdrant holds a searchable vector
projection. The stores do not share a transaction coordinator. Synchronization
must be repeatable, avoid recomputing unchanged embeddings, reject stale vectors
for changed provisions, distinguish full snapshots from partial updates, and
recover safely from interruption at any step.

## Decision

PostgreSQL is authoritative and Qdrant is a derived, rebuildable projection.
The synchronization flow is:

1. Validate the complete input contract before mutation and start a durable
   collection run.
2. Read PostgreSQL identity, hash, collection, and generation state without
   publishing new master rows. Reuse a vector only when its embedding model
   identity, vector schema, and
   embedding input hash all match. Otherwise request a 1024-dimensional
   `bge-m3` embedding.
3. Idempotently stage the Qdrant point, storing `provision_id`, current-state
   marker, hashes, embedding model, and run generation in the allowlisted
   payload. Mark the run `vector_staged` only after Qdrant confirms the write.
4. In one PostgreSQL transaction, upsert authoritative documents, provisions,
   versions, and run items using stable identities and current-text rules; apply
   full-snapshot retirement; then publish the run as succeeded/current.
5. Refresh retired Qdrant payloads as best-effort cleanup and reconcile both
   stores. Complete the run with counts and sanitized item failures. Failed or pending
   items remain retryable without changing identifiers or duplicating points.

There is no distributed two-phase commit. A staged point is not authoritative:
retrieval treats a Qdrant candidate as valid only when its provision is current
in PostgreSQL and the payload's projection identity matches the authoritative
record and active embedding version. A stale, orphaned, or not-yet-published
point is excluded, not served. A reconciliation command
compares IDs, hashes, state, dimensions, and model identity, then repairs or
reports drift idempotently.

Only an explicitly declared full snapshot may retire provisions absent from its
input; a partial synchronization never infers deletion. Retirement or a content
change makes the obsolete vector ineligible before cleanup. Embedding-model or
vector-schema changes build a separate versioned collection and switch the
active collection only after validation.

## Consequences

- Qdrant outage can leave a run incomplete while preserving correct master data;
  affected vectors are unavailable rather than silently stale.
- Synchronization and repair can resume after process, network, or service
  failure without recomputing unchanged vectors.
- Retrieval performs authoritative metadata validation, adding bounded database
  work and explicit degraded-mode behavior.
- Run state and reconciliation metrics are necessary to distinguish fresh,
  pending, failed, stale, and retired projections.
- Orphan cleanup and old collection removal are separate, deliberate operations;
  they are never inferred from a partial run.

## Revisit triggers

- Measured consistency checks or database lookups make request latency exceed
  its service objective and an equally safe projection-version strategy is
  demonstrated.
- The platform adopts a transactional event or outbox mechanism that changes
  retry and reconciliation semantics.
- Qdrant gains an approved authoritative role, or the stores are consolidated;
  either change requires a migration, rollback, and validation plan.
- Collection-scale constraints require multiple points per provision or a
  different point-identity mapping.

## Security implications

Each adapter obtains its own least-privilege runtime credential from documented
environment-variable names. Synchronization logs and run records contain
allowlisted identifiers, hashes, counts, stages, and sanitized errors, never
credentials, authorization headers, credential-bearing URLs, raw environment
data, or secret source details. Qdrant payloads contain no conversation data,
user questions, or secrets. Reconciliation and cleanup operations are scoped,
explicit, non-destructive by default, and never require administrator or
cluster-management credentials from Codex.
