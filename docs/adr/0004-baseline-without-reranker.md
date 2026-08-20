# ADR 0004: No reranker in the initial baseline

- Status: Accepted
- Date: 2026-08-20

## Context

The first usable baseline must preserve the established sequence of vector
retrieval, keyword retrieval, hybrid scoring, configurable Top K, context
extraction, generation, structured validation, and citation validation. Adding
a reranker at the same time as the embedding and vector-store migration would
make regressions harder to attribute and add latency and another remote failure
mode.

## Decision

The initial production profile does not call a reranker. Candidate ordering is
produced solely by the shared deterministic hybrid ranker, with
`reranker_enabled` fixed to false for baseline execution. The profile schema may
reserve this option for experiments, but enabling it is not part of the
baseline contract and must not create an implicit network call.

A future reranker is introduced only as a replaceable application-stage adapter
and only after side-by-side evaluation against the recorded baseline.

## Consequences

- Retrieval behavior remains comparable while infrastructure changes are
  isolated and verified.
- The request path has lower latency, cost, quota use, and operational surface.
- Some ambiguous candidate sets may rank less accurately than they could with a
  proven reranker.
- Evaluation artifacts must record the profile and confirm that reranking was
  disabled.

## Revisit triggers

- The 100-question evaluation or a larger representative dataset identifies a
  repeatable ranking failure that a reranker materially improves.
- Latency, throughput, and gateway quota budgets can absorb the additional
  model call.
- A tested fallback and failure policy exists, along with an ADR updating this
  baseline decision.

## Security implications

Omitting reranking avoids sending questions and retrieved legal text to another
model operation. Any later reranker adapter must use only runtime-injected
credentials, enforce input limits and timeouts, and keep request content and
authorization data out of logs and traces. Evaluation reports must contain no
credential-bearing request metadata.
