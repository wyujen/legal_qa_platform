# ADR 0002: Qdrant instead of pgvector for runtime vector search

- Status: Accepted
- Date: 2026-08-20

## Context

The embedding baseline uses `bge-m3` vectors with exactly 1024 dimensions.
PostgreSQL is already responsible for authoritative legal records, keyword
retrieval, runs, logs, and application data. Keeping runtime vector search in
PostgreSQL would preserve an obsolete infrastructure dependency and combine two
different scaling and indexing concerns.

## Decision

Qdrant is the only runtime vector store. PostgreSQL will not store or query the
production embedding vector for retrieval. Qdrant collections are versioned by
embedding model and vector schema rather than being silently mutated when those
inputs change.

Each point contains the stable `provision_id` plus the minimum metadata needed
to validate and interpret the projection, including content or embedding hash,
current-state marker, and embedding model identity. Legal text and legal status
remain authoritative in PostgreSQL. Vector-store access is behind an
application port so Qdrant client types do not enter the domain layer.

## Consequences

- Qdrant can be operated and tuned independently for vector workloads.
- All retained provisions require new 1024-dimensional embeddings; old vectors
  and NPY artifacts are not reusable.
- The application operates two stores, so ingestion, readiness checks, repair,
  backup planning, and failure handling become explicit concerns.
- Local and CI tests need a replaceable vector-store adapter; live Qdrant tests
  remain separately gated.
- PostgreSQL migrations do not depend on pgvector for application behavior.

## Revisit triggers

- Sustained measurements show Qdrant cannot meet required correctness,
  availability, latency, or operational targets.
- Data volume and operational ownership make a single-store design materially
  safer, supported by a migration and benchmark plan.
- A new embedding representation requires a vector capability Qdrant cannot
  supply without unacceptable complexity.

## Security implications

Qdrant credentials and endpoints are supplied only through documented runtime
environment-variable names and are unwrapped only inside the adapter call.
They must never appear in point payloads, logs, traces, exceptions, fixtures, or
deployment templates. Network authentication and transport policy are operator
responsibilities. Point payloads are allowlisted and must not contain user
questions, conversation data, authorization data, or other secrets.
