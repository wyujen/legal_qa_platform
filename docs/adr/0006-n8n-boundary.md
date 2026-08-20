# ADR 0006: n8n is an external workflow and experiment client

- Status: Accepted
- Date: 2026-08-20

## Context

n8n is useful for visible orchestration, scheduled ingestion, batch evaluation,
prompt experiments, smoke checks, notifications, and administrative workflows.
It is less suitable as the only home of production retrieval, ranking, prompt,
validation, and citation rules because those rules require typed contracts,
repeatable tests, source review, and reuse by several entry points.

## Decision

n8n is outside the application core. It calls versioned FastAPI endpoints or
other explicitly published application interfaces and may orchestrate jobs
around them. It does not reimplement normalization, vector or keyword
retrieval, hybrid ranking, context selection, prompt construction, structured
output validation, or citation allowlisting.

The student-facing QA request path does not require n8n. A workflow may initiate
an ingestion or evaluation run, but the run's semantics and durable state are
owned by `legal_qa_platform` services and PostgreSQL. Removing n8n must leave
the production API and its domain behavior intact.

## Consequences

- The same tested domain implementation serves API, UI, CLI, evaluation, and
  workflow automation.
- Workflows remain easy to change for experiments and operations without
  becoming an unreviewed production engine.
- n8n nodes may contain orchestration mapping, scheduling, and notification
  logic, but not authoritative RAG decisions.
- Workflow failures do not directly corrupt application state when operations
  use idempotent application commands.

## Revisit triggers

- n8n is proposed for a production request path; its availability, licensing,
  latency, retry, and ownership implications require a new decision.
- A workflow needs a capability not expressible through the published API;
  prefer adding a safe application operation before duplicating domain logic.
- The organization replaces n8n; no core-application ADR change should be
  necessary unless the boundary itself changes.

## Security implications

Workflow exports, templates, source control, and execution logs must not contain
credentials, authorization headers, connection strings, raw secret values, or
secret-loading instructions. Runtime authentication is configured by the human
operator using environment-variable references. Workflows receive the minimum
data needed for their task, and application authorization is enforced even for
internal callers. Error and retry metadata is sanitized before persistence.
