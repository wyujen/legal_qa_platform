# ADR 0007: PostgreSQL is the conversation source of truth

- Status: Accepted
- Date: 2026-08-20

## Context

The MVP may begin with limited conversation behavior, but the API and schema
must preserve conversation identity for future multi-user service. Recent chat
messages are conversation context; retrieved legal provisions are RAG context.
Conflating them or leaving durable history only in a framework, cache, workflow,
or telemetry service would weaken ownership, retention, and correctness.

## Decision

PostgreSQL is authoritative for conversations, messages, feedback, and their
application-controlled relationships. Writes use repository methods and
transactions so a message cannot reference a nonexistent conversation and its
ordering is deterministic. The initial context policy may select the latest
configured number of messages, then combine that conversation context with the
current request's separately labeled RAG context.

Langfuse traces, n8n execution history, Streamlit session state, model-provider
history, and any future Redis cache are derived or ephemeral and cannot be the
only copy. Conversation policy is an application service behind a repository
port, not a LangChain, LangGraph, UI, or workflow-specific memory object.

## Consequences

- Conversation history has one transactionally controlled lifecycle and can be
  queried consistently by API and future clients.
- PostgreSQL capacity, retention, deletion, archival, and backup policies must
  be defined before broad production use.
- Recent-message context is deliberately simple; summarization, semantic
  memory, and long-term memory are not implied by this decision.
- Caches may improve performance later but must tolerate eviction and rebuild
  from PostgreSQL.

## Revisit triggers

- Approved scale or residency requirements require partitioning, archival, or a
  dedicated conversation service while preserving authoritative ownership.
- A defined product policy adds summarization or other memory types and needs a
  new schema and provenance rules.
- Retention, deletion, legal hold, or user-mapping requirements become known and
  require a policy ADR.

## Security implications

Conversation content may contain personal or sensitive information. Access is
scoped by authenticated application identity and authorization checks, with
opaque conversation identifiers treated as identifiers rather than access
grants. Raw messages are excluded from normal logs and observability by default.
Retention, deletion, export, backup protection, and encryption requirements are
human-approved production policies. Database credentials remain redacted and
runtime-injected; they never enter domain entities or stored messages.
