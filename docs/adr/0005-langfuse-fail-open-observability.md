# ADR 0005: Langfuse observability is fail-open

- Status: Accepted
- Date: 2026-08-20

## Context

Early tracing is needed to understand normalization, embedding, vector and
keyword retrieval, hybrid ranking, context building, generation, response
validation, and citation validation. Observability is useful for evaluation and
operations, but it is not required to compute a legal QA response. Making it a
synchronous prerequisite would turn telemetry failure into service failure.

## Decision

The application core emits telemetry through an observability port with a
no-operation implementation and an optional Langfuse adapter. Adapter
initialization, span emission, and flush failures are contained at that
boundary. They may produce a sanitized local status signal but do not change a
successful QA result into an error.

The currently approved environment-variable contract contains no Langfuse
configuration names, so the default composition uses the no-operation adapter.
The Langfuse adapter accepts an already configured client and becomes active
only after the runtime contract is explicitly extended; it does not discover
configuration or credentials.

Telemetry operations use bounded queues or calls, explicit short timeouts, and
no unbounded retry on the request path. The allowlist covers operational fields
such as span name, latency, model identifier, prompt version, profile and
retrieval parameters, stable provision IDs, scores, and validation outcomes.
Raw question, answer, conversation, prompt, and context content is omitted by
default and may be enabled only under an explicit data-handling and retention
policy.

## Consequences

- QA remains available during Langfuse outage, configuration error, or network
  partition.
- Traces may be incomplete or absent; local metrics must make telemetry loss
  visible without exposing request content.
- Instrumentation remains testable independently from the Langfuse SDK.
- Trace delivery is best-effort and is not an audit log or conversation store.

## Revisit triggers

- An approved audit requirement needs durable event delivery; that requirement
  should use a separate reliable audit path rather than blocking answers on
  Langfuse.
- Telemetry loss prevents operation of agreed service objectives and a bounded,
  resilient delivery design is available.
- Data-governance policy explicitly changes which content fields may be traced.

## Security implications

No Langfuse credential name is currently approved, so no credential is read by
the default composition or represented in deployment templates. If the runtime
contract is later extended, its credentials must use documented names,
redacting types, and adapter-only unwrapping. Authorization headers, settings,
connection URLs containing credentials, prompts, user content, and conversation
content are excluded unless explicitly allowlisted by policy. Telemetry
exceptions are sanitized before local logging. Langfuse is never the source of
truth for application or conversation data.
