# legal_qa_platform Codex Instructions

## Scope and project identity

- The only official project name is `legal_qa_platform`. Do not introduce `v2` or other suffixes in package, image, runtime, path, or new document names.
- Write application code, data, tests, migrations, deployment templates, and documentation only in this repository.
- `C:\Users\wyujen.SD\code\sample\legal-qa` is a read-only reference. Never modify it and never create an import, link, path, build, test, or runtime dependency on it.
- Assets retained from the reference repository must be copied into this repository or reimplemented here and verified for independent operation.

## Security and secrets

- Treat runtime credentials as externally injected environment variables. Only rely on names documented in this repository's environment-variable contract.
- Never request, discover, read, display, print, log, commit, or persist real credentials.
- Do not search for `.env` files, credential files, secret directories, shell profiles, credential stores, secret-loading scripts, or the human operator's secret-management process.
- Never dump the environment, unredacted settings, request headers, authorization headers, API keys, passwords, salts, cookies, private keys, tokens, or credential-bearing connection strings.
- Do not request administrator, superuser, master-key, kubeconfig, or cluster-admin credential values. The only approved database-administrator inputs are the documented `POSTGRES_ADMIN_USER`, `POSTGRES_ADMIN_PASSWORD`, and `POSTGRES_ADMIN_DATABASE` names, read from the current process by the explicit one-shot migration command.
- Sensitive settings must use redacting types, stay outside domain models, and be unwrapped only at the adapter call that needs them.
- If required variables already exist, tests may use them without revealing values or sources. If they do not exist, provide a safe command for the human operator; do not ask for credentials.
- Smoke tests must accept credentials only from the current process environment and must not expose credential flags such as `--api-key`, `--password`, or `--secret-file`.
- Docker and Kubernetes files contain only environment-variable references, `secretKeyRef` references, or explicit placeholders. Real deployment values, namespaces, and Secret provisioning belong to the human operator.
- Logs, exceptions, traces, diagnostics, and test output must be allowlisted or redacted. Observability must never receive secrets.
- Keep PostgreSQL identities separated: `POSTGRES_ADMIN_*` is operator-only DDL for explicit migration/bootstrap, while `POSTGRES_LITELLM_*` is the least-privilege application identity for runtime DML. API, sync, smoke, evaluation, load-test, UI, and normal deployment processes must never require or receive `POSTGRES_ADMIN_*`.

## Baseline architecture and behavior

- Python owns the RAG application core and explicit domain/service/adapter contracts. Framework types must not leak into the domain layer.
- PostgreSQL is the source of truth for legal master data, keyword retrieval, sync runs/logs, conversations, messages, and feedback. It is not the runtime vector store.
- Qdrant stores `bge-m3` 1024-dimensional vectors. LiteLLM REST provides `bge-m3` embeddings and `campus-qa` answers; chat calls must send `max_tokens`.
- Preserve stable `provision_id`, global `sort_order`, article semantics, current-text rules, content/embedding hashes, full-versus-partial sync, hybrid retrieval, configurable Top K, context extraction, structured output, citation allowlisting, validation, and the 100-question evaluation dataset.
- Langfuse observability is fail-open and must not become a QA hard dependency. Conversation data remains application-controlled in PostgreSQL.
- Streamlit is an HTTP client of the REST API and must not import the QA service directly.
- The baseline does not use Ollama, embeddinggemma, Gemma 4, pgvector vector storage, NPY embeddings, reranking, Redis, LangGraph, agents, long-term memory, automatic law collection, or duplicated n8n RAG logic.

## Engineering practice

- Prefer small, typed modules with documented input, output, external dependency, configuration, failure mode, and test boundary.
- Keep one implementation of retrieval, ranking, prompt, and validation behavior shared by CLI, API, UI, and evaluation.
- Add or update unit tests with each core behavior. Keep live integration tests explicitly gated by the documented runtime-variable names and safe to skip.
- Migrations and synchronization must be repeatable and non-destructive by default. The migration command may use the documented operator-only admin identity solely in the matching target database and `legal_qa` schema, then grant the existing runtime identity only the required schema, table, and sequence privileges. It must not create, alter, or drop roles/databases or alter unrelated LiteLLM objects.
- Record replaceable architecture choices and unresolved production policy in ADRs or documentation rather than hard-coding them.
- Before handoff, run available unit, static, build, data-contract, independence, and secret-safety checks; report any live checks that could not run because runtime configuration was absent.
