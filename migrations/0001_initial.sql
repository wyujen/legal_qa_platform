-- migration-version: 0001_initial.sql
-- legal_qa_platform baseline schema.
-- PostgreSQL is the source of truth for identities, current legal text,
-- synchronization state, QA runs, conversations, and feedback. Vectors are
-- intentionally absent: they live in Qdrant.
-- Execute this entire file with DBeaver's "Execute SQL Script" action. The
-- transaction records migration history only after every schema statement has
-- succeeded. This file intentionally contains no role, user, database, grant,
-- or revoke statement; privileges remain a Human Operator responsibility.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('legal_qa_platform:migrations', 0)
);

CREATE SCHEMA IF NOT EXISTS legal_qa;

CREATE SEQUENCE IF NOT EXISTS legal_qa.sync_generation_seq AS bigint;

CREATE TABLE IF NOT EXISTS legal_qa.schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS legal_qa.collection_runs (
    run_id uuid PRIMARY KEY,
    generation bigint NOT NULL UNIQUE
        DEFAULT nextval('legal_qa.sync_generation_seq'),
    mode text NOT NULL CHECK (mode IN ('full_snapshot', 'partial')),
    status text NOT NULL CHECK (
        status IN ('running', 'vector_staged', 'succeeded', 'failed')
    ),
    source_label text NOT NULL,
    source_fingerprint char(64) NOT NULL,
    embedding_model text NOT NULL,
    embedding_dimension integer NOT NULL CHECK (embedding_dimension > 0),
    vector_collection text NOT NULL,
    document_count integer NOT NULL DEFAULT 0 CHECK (document_count >= 0),
    provision_count integer NOT NULL DEFAULT 0 CHECK (provision_count >= 0),
    embedded_count integer NOT NULL DEFAULT 0 CHECK (embedded_count >= 0),
    reused_vector_count integer NOT NULL DEFAULT 0
        CHECK (reused_vector_count >= 0),
    deactivated_count integer NOT NULL DEFAULT 0
        CHECK (deactivated_count >= 0),
    error_category text,
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    CHECK (
        (status IN ('running', 'vector_staged') AND completed_at IS NULL)
        OR (status IN ('succeeded', 'failed') AND completed_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS collection_runs_status_started_idx
    ON legal_qa.collection_runs (status, started_at DESC);

CREATE TABLE IF NOT EXISTS legal_qa.legal_documents (
    document_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_name text NOT NULL UNIQUE,
    canonical_document_name text NOT NULL UNIQUE,
    source_url text NOT NULL DEFAULT '',
    official_content_hash char(64) NOT NULL,
    is_current boolean NOT NULL DEFAULT true,
    first_seen_run_id uuid NOT NULL
        REFERENCES legal_qa.collection_runs(run_id),
    last_seen_run_id uuid NOT NULL
        REFERENCES legal_qa.collection_runs(run_id),
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS legal_qa.provision_identity_ledger (
    provision_id bigint PRIMARY KEY CHECK (provision_id > 0),
    canonical_stable_key char(64) UNIQUE,
    document_name text,
    article_no text,
    paragraph_no integer CHECK (paragraph_no IS NULL OR paragraph_no > 0),
    subparagraph_no integer
        CHECK (subparagraph_no IS NULL OR subparagraph_no > 0),
    identity_status text NOT NULL CHECK (
        identity_status IN ('current', 'retired', 'reserved_legacy')
    ),
    first_seen_run_id uuid REFERENCES legal_qa.collection_runs(run_id),
    retired_run_id uuid REFERENCES legal_qa.collection_runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (identity_status = 'reserved_legacy'
         AND canonical_stable_key IS NULL
         AND document_name IS NULL
         AND article_no IS NULL)
        OR
        (identity_status <> 'reserved_legacy'
         AND canonical_stable_key IS NOT NULL
         AND document_name IS NOT NULL
         AND article_no IS NOT NULL)
    )
);

-- IDs 1..8 were retired before the checked-in active snapshot. Reserve them
-- without inventing their missing historical stable keys, so they can never be
-- silently reused by a database reconstructed from the active JSON.
INSERT INTO legal_qa.provision_identity_ledger (
    provision_id,
    identity_status
)
SELECT legacy_id, 'reserved_legacy'
FROM generate_series(1, 8) AS legacy_id
ON CONFLICT (provision_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS legal_qa.legal_provisions (
    provision_id bigint PRIMARY KEY
        REFERENCES legal_qa.provision_identity_ledger(provision_id),
    document_id bigint NOT NULL
        REFERENCES legal_qa.legal_documents(document_id),
    canonical_stable_key char(64) NOT NULL UNIQUE,
    chapter_name text NOT NULL DEFAULT '',
    section_name text NOT NULL DEFAULT '',
    article_no text NOT NULL,
    paragraph_no integer CHECK (paragraph_no IS NULL OR paragraph_no > 0),
    subparagraph_no integer
        CHECK (subparagraph_no IS NULL OR subparagraph_no > 0),
    title text NOT NULL DEFAULT '',
    content text NOT NULL CHECK (length(content) > 0),
    search_text text NOT NULL CHECK (length(search_text) > 0),
    search_compact text NOT NULL CHECK (length(search_compact) > 0),
    sort_order integer NOT NULL CHECK (sort_order > 0),
    source_url text NOT NULL DEFAULT '',
    official_content_hash char(64) NOT NULL,
    record_hash char(64) NOT NULL,
    embedding_input_hash char(64) NOT NULL,
    embedding_model text NOT NULL,
    vector_collection text NOT NULL,
    vector_generation bigint NOT NULL,
    is_current boolean NOT NULL DEFAULT true,
    first_seen_run_id uuid NOT NULL
        REFERENCES legal_qa.collection_runs(run_id),
    last_seen_run_id uuid NOT NULL
        REFERENCES legal_qa.collection_runs(run_id),
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS legal_provisions_current_sort_idx
    ON legal_qa.legal_provisions (sort_order, provision_id)
    WHERE is_current;
CREATE INDEX IF NOT EXISTS legal_provisions_document_current_idx
    ON legal_qa.legal_provisions (document_id, sort_order)
    WHERE is_current;
-- Baseline keyword retrieval uses deterministic compact phrase/bigram matching.
-- A future FTS/trigram migration may add an index without changing its port.
CREATE INDEX IF NOT EXISTS legal_provisions_search_prefix_idx
    ON legal_qa.legal_provisions (search_compact text_pattern_ops)
    WHERE is_current;

CREATE TABLE IF NOT EXISTS legal_qa.legal_provision_versions (
    provision_id bigint NOT NULL
        REFERENCES legal_qa.provision_identity_ledger(provision_id),
    record_hash char(64) NOT NULL,
    collection_run_id uuid NOT NULL
        REFERENCES legal_qa.collection_runs(run_id),
    document_name text NOT NULL,
    article_no text NOT NULL,
    official_content_hash char(64) NOT NULL,
    embedding_input_hash char(64) NOT NULL,
    record jsonb NOT NULL,
    collected_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (provision_id, record_hash)
);

CREATE INDEX IF NOT EXISTS legal_provision_versions_run_idx
    ON legal_qa.legal_provision_versions (collection_run_id, provision_id);

CREATE TABLE IF NOT EXISTS legal_qa.collection_run_items (
    run_id uuid NOT NULL REFERENCES legal_qa.collection_runs(run_id),
    provision_id bigint NOT NULL CHECK (provision_id > 0),
    embedding_input_hash char(64) NOT NULL,
    vector_action text NOT NULL CHECK (
        vector_action IN ('upserted', 'reused', 'deactivated')
    ),
    PRIMARY KEY (run_id, provision_id)
);

CREATE TABLE IF NOT EXISTS legal_qa.conversations (
    conversation_id uuid PRIMARY KEY,
    user_id text,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'closed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS legal_qa.messages (
    message_id uuid PRIMARY KEY,
    conversation_id uuid NOT NULL
        REFERENCES legal_qa.conversations(conversation_id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content text NOT NULL CHECK (length(content) > 0),
    query_id uuid,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS messages_conversation_created_idx
    ON legal_qa.messages (conversation_id, created_at DESC, message_id DESC);

CREATE TABLE IF NOT EXISTS legal_qa.qa_runs (
    query_id uuid PRIMARY KEY,
    conversation_id uuid
        REFERENCES legal_qa.conversations(conversation_id),
    trace_id text,
    profile_name text NOT NULL,
    prompt_name text NOT NULL,
    normalization_version text NOT NULL,
    chat_model text NOT NULL,
    embedding_model text NOT NULL,
    vector_collection text NOT NULL,
    question text NOT NULL,
    normalized_question text NOT NULL,
    status text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    response jsonb,
    stage_latencies_ms jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_category text,
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    CHECK (
        (status = 'running' AND completed_at IS NULL)
        OR (status IN ('succeeded', 'failed') AND completed_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS qa_runs_started_idx
    ON legal_qa.qa_runs (started_at DESC);

CREATE TABLE IF NOT EXISTS legal_qa.qa_retrievals (
    query_id uuid NOT NULL
        REFERENCES legal_qa.qa_runs(query_id) ON DELETE CASCADE,
    rank integer NOT NULL CHECK (rank > 0),
    provision_id bigint NOT NULL
        REFERENCES legal_qa.provision_identity_ledger(provision_id),
    vector_score double precision NOT NULL,
    keyword_score double precision NOT NULL,
    final_score double precision NOT NULL,
    official_content_hash char(64) NOT NULL,
    record_hash char(64) NOT NULL,
    embedding_input_hash char(64) NOT NULL,
    excerpt_hash char(64),
    PRIMARY KEY (query_id, rank),
    UNIQUE (query_id, provision_id)
);

CREATE TABLE IF NOT EXISTS legal_qa.feedback (
    feedback_id uuid PRIMARY KEY,
    query_id uuid NOT NULL REFERENCES legal_qa.qa_runs(query_id),
    conversation_id uuid REFERENCES legal_qa.conversations(conversation_id),
    rating smallint CHECK (rating IN (-1, 1)),
    category text,
    comment text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (rating IS NOT NULL OR category IS NOT NULL OR comment IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS feedback_query_idx
    ON legal_qa.feedback (query_id, created_at DESC);

-- Keep this as the final statement before COMMIT. A failed statement above
-- aborts the transaction, so an incomplete migration is never recorded.
INSERT INTO legal_qa.schema_migrations (version)
VALUES ('0001_initial.sql')
ON CONFLICT (version) DO NOTHING;

COMMIT;
