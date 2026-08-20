# ADR 0001: FastAPI as the REST delivery boundary

- Status: Accepted
- Date: 2026-08-20

## Context

`legal_qa_platform` needs one stable application interface for Streamlit,
workflow tools, and future student-facing clients. Python owns the RAG core,
but transport framework concepts must not determine retrieval, prompt,
validation, or citation behavior. The model and embedding endpoints exposed by
LiteLLM are dependencies of the application, not its public API.

## Decision

FastAPI is the inbound REST adapter for the application. Versioned application
routes currently expose chat, retrieval, feedback, health, and readiness.
Future experiment or batch operations require an explicit versioned contract;
they are not implied by this decision.

Endpoint handlers will validate transport schemas, translate them to typed
application commands, call framework-independent services, and map results or
known failures back to HTTP. FastAPI request, response, dependency-injection,
and exception types must not enter the domain or application-service layers.

Streamlit and n8n call the REST API over HTTP and do not import the QA service.
CLI and evaluation entry points may call the same application services through
their public Python interfaces; they must not duplicate pipeline logic.

## Consequences

- OpenAPI and conventional HTTP tooling are available with little adapter code.
- The RAG core remains testable without starting a web server.
- Transport validation and domain validation remain distinct test boundaries.
- The API adapter must explicitly map timeouts, unavailable dependencies,
  validation failures, and unexpected failures to stable responses.
- Replacing FastAPI requires a new inbound adapter, not a rewrite of the RAG
  pipeline.

## Revisit triggers

- A required client protocol cannot be represented safely or efficiently over
  the versioned REST interface.
- Measured transport overhead, streaming needs, or deployment constraints make
  a different server framework materially better.
- A platform gateway takes ownership of the public contract; the Python API may
  then become an internal service while preserving the application ports.

## Security implications

Authentication, authorization, CORS, rate limits, and public exposure are
deployment policies at the API boundary and must not be bypassed by UI or
workflow clients. Credentials come only from the documented runtime environment
contract and use redacting settings types. Request headers, authorization data,
raw settings, credential-bearing URLs, and raw request bodies are not logged by
default. Error responses and OpenAPI examples must contain no deployment
credentials or secret values.
