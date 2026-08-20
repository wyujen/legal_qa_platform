-- legal_qa_platform baseline migration post-check.
-- This file is read-only. Run it in DBeaver only after 0001_initial.sql reports
-- COMMIT. Every returned row must have passed = true.

WITH expected_tables(table_name) AS (
    VALUES
        ('schema_migrations'),
        ('collection_runs'),
        ('legal_documents'),
        ('provision_identity_ledger'),
        ('legal_provisions'),
        ('legal_provision_versions'),
        ('collection_run_items'),
        ('conversations'),
        ('messages'),
        ('qa_runs'),
        ('qa_retrievals'),
        ('feedback')
),
expected_indexes(index_name) AS (
    VALUES
        ('collection_runs_status_started_idx'),
        ('legal_provisions_current_sort_idx'),
        ('legal_provisions_document_current_idx'),
        ('legal_provisions_search_prefix_idx'),
        ('legal_provision_versions_run_idx'),
        ('messages_conversation_created_idx'),
        ('qa_runs_started_idx'),
        ('feedback_query_idx')
),
checks(check_name, passed) AS (
    SELECT
        'migration_history',
        EXISTS (
            SELECT 1
            FROM legal_qa.schema_migrations
            WHERE version = '0001_initial.sql'
        )
    UNION ALL
    SELECT
        'expected_tables',
        NOT EXISTS (
            SELECT 1
            FROM expected_tables AS expected
            LEFT JOIN information_schema.tables AS actual
                ON actual.table_schema = 'legal_qa'
               AND actual.table_name = expected.table_name
            WHERE actual.table_name IS NULL
        )
    UNION ALL
    SELECT
        'expected_indexes',
        NOT EXISTS (
            SELECT 1
            FROM expected_indexes AS expected
            LEFT JOIN pg_catalog.pg_indexes AS actual
                ON actual.schemaname = 'legal_qa'
               AND actual.indexname = expected.index_name
            WHERE actual.indexname IS NULL
        )
    UNION ALL
    SELECT
        'sync_generation_sequence',
        to_regclass('legal_qa.sync_generation_seq') IS NOT NULL
    UNION ALL
    SELECT
        'reserved_legacy_ids',
        (
            SELECT count(*) = 8
            FROM legal_qa.provision_identity_ledger
            WHERE provision_id BETWEEN 1 AND 8
              AND identity_status = 'reserved_legacy'
        )
    UNION ALL
    SELECT
        'no_pgvector_columns',
        NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'legal_qa'
              AND udt_name = 'vector'
        )
)
SELECT check_name, passed
FROM checks
ORDER BY check_name;
