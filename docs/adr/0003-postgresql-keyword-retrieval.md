# ADR 0003: PostgreSQL for keyword retrieval

- Status: Accepted
- Date: 2026-08-20

## Context

Semantic similarity alone is not sufficient for legal citations, article
numbers, exact phrases, and Chinese lexical matches. The proven retrieval flow
combines vector candidates with full-phrase and Chinese-bigram keyword
candidates before deterministic hybrid ranking. PostgreSQL already holds the
authoritative current legal text.

## Decision

PostgreSQL provides keyword candidates from application-owned legal tables.
The initial adapter preserves the validated phrase and bigram behavior and
returns authoritative snapshots keyed by stable `provision_id`, ordered by
phrase and matched-term signals. It searches only records eligible under the
current-text rules; Python recomputes the exact lexical score from those local
master records before hybrid ranking.

The Python application core owns normalization of candidate scores, vector and
keyword weighting, deduplication, minimum score, and configurable Top K. SQL,
index definitions, and database-specific query details stay in the PostgreSQL
adapter. UI, API, CLI, evaluation, and n8n must not implement alternate keyword
or hybrid-ranking logic.

Migrations create only objects in the application's database and `legal_qa`
schema. A repository command validates the SQL offline but never connects or
applies it. The Human Operator executes the transactional, checked-in script
through an existing DBeaver administrative connection and assigns the runtime
capability allowlist through database administration UI. Repository SQL has no
role/user/database values, placeholders, or grants. The baseline does not
silently depend on an optional extension or provision roles/databases.

## Consequences

- Keyword results read the same legal text and current-state flags as the
  master-data repository, avoiding a third search index.
- Exact legal terms complement Qdrant semantic candidates and preserve a
  comparable baseline.
- PostgreSQL carries query and indexing load that must be measured and tuned.
- Database scoring details require contract tests so migrations and query
  changes do not silently alter ranking behavior.

## Revisit triggers

- Corpus size or measured query latency exceeds PostgreSQL's agreed service
  target after reasonable indexing and query tuning.
- Evaluation shows a specialized lexical engine yields a material, repeatable
  quality gain worth another consistency boundary.
- Language-analysis requirements outgrow the phrase and bigram baseline.

## Security implications

All queries are parameterized; user text is never interpolated into SQL.
Runtime database access uses an application-scoped identity supplied through
the runtime environment contract. Administrator credentials remain wholly
outside the project in the Human Operator's DBeaver setup; migration validation
reads repository files only. Query diagnostics expose allowlisted timings,
counts, categories, and stable provision identifiers rather than raw
credentials, connection strings, database names, or question text. Optional
database features must not prompt the runtime application to acquire
administrator privileges.
