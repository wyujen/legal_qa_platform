# Architecture Decision Records

This directory records durable architecture decisions for `legal_qa_platform`.
An ADR is updated only to clarify its meaning; a changed decision receives a
new ADR that supersedes the old one.

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-fastapi-rest-boundary.md) | FastAPI as the REST delivery boundary | Accepted |
| [0002](0002-qdrant-vector-store.md) | Qdrant instead of pgvector for runtime vector search | Accepted |
| [0003](0003-postgresql-keyword-retrieval.md) | PostgreSQL for keyword retrieval | Accepted |
| [0004](0004-baseline-without-reranker.md) | No reranker in the initial baseline | Accepted |
| [0005](0005-langfuse-fail-open-observability.md) | Langfuse observability is fail-open | Accepted |
| [0006](0006-n8n-boundary.md) | n8n is an external workflow and experiment client | Accepted |
| [0007](0007-postgresql-conversation-source-of-truth.md) | PostgreSQL is the conversation source of truth | Accepted |
| [0008](0008-postgresql-qdrant-consistency.md) | PostgreSQL/Qdrant cross-store consistency model | Accepted |
