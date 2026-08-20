"""PostgreSQL repository for legal master data and application records.

No connection string is ever assembled or logged. The adapter receives a pool
whose keyword arguments were built from already validated runtime settings.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from legal_qa_platform.config import RuntimeSettings
from legal_qa_platform.domain.legal import (
    LegalProvision,
    canonical_json_hash,
    canonicalize_identity_text,
)
from legal_qa_platform.errors import ExternalServiceError, IdentityConflictError
from legal_qa_platform.ports.repositories import (
    ProvisionSnapshot,
    ProvisionSyncState,
    ProvisionWrite,
    PublishSummary,
    SyncRun,
)


def create_postgres_pool(
    settings: RuntimeSettings,
    *,
    min_size: int = 1,
    max_size: int = 10,
) -> AsyncConnectionPool[Any]:
    """Build a closed pool after fail-fast validation, without a printable DSN."""

    endpoint = settings.require_postgres()
    assert settings.postgres_user is not None
    assert settings.postgres_password is not None
    assert settings.postgres_database is not None
    return AsyncConnectionPool(
        conninfo="",
        kwargs={
            "host": endpoint.host,
            "port": endpoint.port,
            "user": settings.postgres_user,
            "password": settings.postgres_password.get_secret_value(),
            "dbname": settings.postgres_database,
        },
        min_size=min_size,
        max_size=max_size,
        timeout=2.0,
        open=False,
        name="legal_qa_platform",
    )


def _safe_database_error(exc: Exception) -> ExternalServiceError:
    name = type(exc).__name__.casefold()
    if "timeout" in name:
        category = "timeout"
    elif "permission" in name or "privilege" in name:
        category = "permission_denied"
    elif "auth" in name or "password" in name:
        category = "authentication_failed"
    else:
        category = "database_error"
    return ExternalServiceError("postgresql", category)


def _stable_key_transition_allowed(
    state: ProvisionSyncState,
    incoming: LegalProvision,
) -> bool:
    """Allow only the documented unsplit-to-first-paragraph identity migration."""

    return (
        state.document_name == incoming.document_name
        and state.article_no == incoming.article_no
        and state.paragraph_no is None
        and incoming.paragraph_no == 1
        and state.subparagraph_no == incoming.subparagraph_no
    )


def _row_to_provision(row: Mapping[str, Any]) -> LegalProvision:
    return LegalProvision.model_validate(
        {
            "provision_id": row["provision_id"],
            "document_name": row["document_name"],
            "chapter_name": row["chapter_name"],
            "section_name": row["section_name"],
            "article_no": row["article_no"],
            "paragraph_no": row["paragraph_no"],
            "subparagraph_no": row["subparagraph_no"],
            "title": row["title"],
            "content": row["content"],
            "search_text": row["search_text"],
            "sort_order": row["sort_order"],
            "source_url": row["source_url"],
            "is_active": row["is_current"],
        }
    )


class PostgresRepository:
    """Async repository; all public failures are classified and redacted."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def open(self) -> None:
        try:
            # Start connection workers without making process startup depend on
            # current database availability. Readiness owns dependency state.
            await self._pool.open(wait=False)
        except Exception as exc:
            raise _safe_database_error(exc) from None

    async def close(self) -> None:
        await self._pool.close()

    async def is_ready(self) -> bool:
        try:
            async with self._pool.connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        "SELECT to_regclass('legal_qa.legal_provisions')"
                    )
                    row = await cursor.fetchone()
                    return bool(row and row[0])
        except Exception:
            return False

    async def has_published_snapshot(
        self,
        *,
        embedding_model: str,
        embedding_dimension: int,
        vector_collection: str,
    ) -> bool:
        """Confirm that this profile has a successful, current master snapshot."""

        try:
            async with self._pool.connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM legal_qa.collection_runs AS r
                            WHERE r.status = 'succeeded'
                              AND r.embedding_model = %s
                              AND r.embedding_dimension = %s
                              AND r.vector_collection = %s
                              AND EXISTS (
                                  SELECT 1
                                  FROM legal_qa.legal_provisions AS p
                                  WHERE p.is_current
                                    AND p.embedding_model = r.embedding_model
                                    AND p.vector_collection = r.vector_collection
                              )
                        )
                        """,
                        (
                            embedding_model,
                            embedding_dimension,
                            vector_collection,
                        ),
                    )
                    row = await cursor.fetchone()
                    return bool(row and row[0])
        except Exception:
            return False

    async def apply_migrations(self, directory: Path) -> tuple[str, ...]:
        """Apply ordered SQL files transactionally and return newly applied names."""

        files = await asyncio.to_thread(lambda: sorted(directory.glob("*.sql")))
        if not files:
            raise ValueError("No migration files found.")
        applied_now: list[str] = []
        try:
            async with self._pool.connection() as connection:
                async with connection.transaction():
                    async with connection.cursor() as cursor:
                        await cursor.execute("CREATE SCHEMA IF NOT EXISTS legal_qa")
                        await cursor.execute(
                            """
                            CREATE TABLE IF NOT EXISTS legal_qa.schema_migrations (
                                version text PRIMARY KEY,
                                applied_at timestamptz NOT NULL DEFAULT now()
                            )
                            """
                        )
                        await cursor.execute(
                            "SELECT version FROM legal_qa.schema_migrations"
                        )
                        applied = {row[0] for row in await cursor.fetchall()}
                        for path in files:
                            if path.name in applied:
                                continue
                            sql = path.read_text(encoding="utf-8")
                            await cursor.execute(sql, prepare=False)
                            await cursor.execute(
                                """
                                INSERT INTO legal_qa.schema_migrations (version)
                                VALUES (%s)
                                ON CONFLICT (version) DO NOTHING
                                """,
                                (path.name,),
                            )
                            applied_now.append(path.name)
        except Exception as exc:
            raise _safe_database_error(exc) from None
        return tuple(applied_now)

    async def start_collection_run(
        self,
        *,
        mode: Literal["full_snapshot", "partial"],
        source_label: str,
        source_fingerprint: str,
        embedding_model: str,
        embedding_dimension: int,
        vector_collection: str,
        document_count: int,
        provision_count: int,
    ) -> SyncRun:
        run_id = uuid4()
        try:
            async with self._pool.connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO legal_qa.collection_runs (
                            run_id, mode, status, source_label,
                            source_fingerprint, embedding_model,
                            embedding_dimension, vector_collection,
                            document_count, provision_count
                        ) VALUES (
                            %s, %s, 'running', %s, %s, %s, %s, %s, %s, %s
                        )
                        RETURNING generation
                        """,
                        (
                            run_id,
                            mode,
                            source_label,
                            source_fingerprint,
                            embedding_model,
                            embedding_dimension,
                            vector_collection,
                            document_count,
                            provision_count,
                        ),
                    )
                    row = await cursor.fetchone()
                await connection.commit()
        except Exception as exc:
            raise _safe_database_error(exc) from None
        if row is None:
            raise ExternalServiceError("postgresql", "missing_run_generation")
        return SyncRun(run_id=run_id, generation=int(row[0]))

    async def mark_vectors_staged(
        self,
        run_id: UUID,
        *,
        embedded_count: int,
        reused_vector_count: int,
    ) -> None:
        try:
            async with self._pool.connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE legal_qa.collection_runs
                        SET status = 'vector_staged',
                            embedded_count = %s,
                            reused_vector_count = %s
                        WHERE run_id = %s AND status = 'running'
                        """,
                        (embedded_count, reused_vector_count, run_id),
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError("invalid collection run transition")
                await connection.commit()
        except Exception as exc:
            raise _safe_database_error(exc) from None

    async def mark_run_failed(self, run_id: UUID, category: str) -> None:
        """Persist a safe failure category in a separate transaction."""

        safe_category = (
            "".join(
                character
                for character in category[:100]
                if character.isalnum() or character in {"_", "-"}
            )
            or "unknown"
        )
        try:
            async with self._pool.connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE legal_qa.collection_runs
                        SET status = 'failed', error_category = %s,
                            completed_at = now()
                        WHERE run_id = %s
                          AND status IN ('running', 'vector_staged')
                        """,
                        (safe_category, run_id),
                    )
                await connection.commit()
        except Exception as exc:
            raise _safe_database_error(exc) from None

    async def get_sync_states(
        self, provision_ids: Sequence[int]
    ) -> dict[int, ProvisionSyncState]:
        if not provision_ids:
            return {}
        try:
            async with self._pool.connection() as connection:
                async with connection.cursor(row_factory=dict_row) as cursor:
                    await cursor.execute(
                        """
                        SELECT i.provision_id, i.canonical_stable_key,
                               i.document_name, i.article_no,
                               i.paragraph_no, i.subparagraph_no,
                               i.identity_status, p.record_hash,
                               p.embedding_input_hash, p.embedding_model,
                               p.vector_collection, p.vector_generation,
                               COALESCE(p.is_current, false) AS is_current
                        FROM legal_qa.provision_identity_ledger AS i
                        LEFT JOIN legal_qa.legal_provisions AS p
                          ON p.provision_id = i.provision_id
                        WHERE i.provision_id = ANY(%s::bigint[])
                        """,
                        (list(dict.fromkeys(provision_ids)),),
                    )
                    rows = await cursor.fetchall()
        except Exception as exc:
            raise _safe_database_error(exc) from None
        return {int(row["provision_id"]): ProvisionSyncState(**row) for row in rows}

    async def get_max_provision_id(self) -> int:
        try:
            async with self._pool.connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        "SELECT COALESCE(max(provision_id), 0) "
                        "FROM legal_qa.provision_identity_ledger"
                    )
                    row = await cursor.fetchone()
        except Exception as exc:
            raise _safe_database_error(exc) from None
        return int(row[0]) if row else 0

    async def publish_snapshot(
        self,
        run: SyncRun,
        writes: Sequence[ProvisionWrite],
        *,
        full_snapshot: bool,
    ) -> PublishSummary:
        """Atomically publish master data after Qdrant vectors were staged.

        Retrieval later verifies Qdrant payload hashes against these rows, so a
        Qdrant orphan from a failed transaction cannot become trusted context.
        """

        if not writes:
            raise ValueError("Refusing to publish an empty snapshot.")
        ids = [item.provision.provision_id for item in writes]
        keys = [item.canonical_stable_key for item in writes]
        if len(ids) != len(set(ids)) or len(keys) != len(set(keys)):
            raise IdentityConflictError("Incoming IDs and stable keys must be unique.")

        grouped: dict[str, list[ProvisionWrite]] = defaultdict(list)
        for item in writes:
            grouped[item.provision.document_name].append(item)

        try:
            async with self._pool.connection() as connection:
                async with connection.transaction():
                    async with connection.cursor(row_factory=dict_row) as cursor:
                        await cursor.execute(
                            """
                            SELECT status, generation, embedding_model,
                                   vector_collection
                            FROM legal_qa.collection_runs
                            WHERE run_id = %s
                            FOR UPDATE
                            """,
                            (run.run_id,),
                        )
                        run_row = await cursor.fetchone()
                        if (
                            run_row is None
                            or run_row["status"] != "vector_staged"
                            or int(run_row["generation"]) != run.generation
                        ):
                            raise IdentityConflictError(
                                "Collection run is not ready to publish."
                            )

                        await cursor.execute(
                            """
                            SELECT provision_id, canonical_stable_key,
                                   document_name, article_no, paragraph_no,
                                   subparagraph_no, identity_status
                            FROM legal_qa.provision_identity_ledger
                            WHERE provision_id = ANY(%s::bigint[])
                               OR canonical_stable_key = ANY(%s::char(64)[])
                            FOR UPDATE
                            """,
                            (ids, keys),
                        )
                        identity_rows = await cursor.fetchall()
                        states_by_id = {
                            int(row["provision_id"]): ProvisionSyncState(
                                provision_id=int(row["provision_id"]),
                                canonical_stable_key=row["canonical_stable_key"],
                                document_name=row["document_name"],
                                article_no=row["article_no"],
                                paragraph_no=row["paragraph_no"],
                                subparagraph_no=row["subparagraph_no"],
                                identity_status=row["identity_status"],
                                record_hash=None,
                                embedding_input_hash=None,
                                embedding_model=None,
                                vector_collection=None,
                                vector_generation=None,
                                is_current=False,
                            )
                            for row in identity_rows
                            if int(row["provision_id"]) in set(ids)
                        }
                        incoming_by_id = {
                            item.provision.provision_id: item for item in writes
                        }
                        for row in identity_rows:
                            key = row["canonical_stable_key"]
                            matching = next(
                                (
                                    item
                                    for item in writes
                                    if item.canonical_stable_key == key
                                ),
                                None,
                            )
                            if (
                                matching
                                and int(row["provision_id"])
                                != matching.provision.provision_id
                            ):
                                raise IdentityConflictError(
                                    "A stable provision key is already assigned "
                                    "to another ID."
                                )

                        await cursor.execute(
                            "SELECT COALESCE(max(provision_id), 0) AS max_id "
                            "FROM legal_qa.provision_identity_ledger"
                        )
                        max_existing = int((await cursor.fetchone())["max_id"])
                        for provision_id, item in incoming_by_id.items():
                            state = states_by_id.get(provision_id)
                            if state is None:
                                if provision_id <= max_existing:
                                    raise IdentityConflictError(
                                        "A new provision ID would reuse "
                                        "historical ID space."
                                    )
                                continue
                            if state.identity_status == "reserved_legacy":
                                raise IdentityConflictError(
                                    "A retired legacy provision ID cannot be reused."
                                )
                            if (
                                state.canonical_stable_key != item.canonical_stable_key
                                and not _stable_key_transition_allowed(
                                    state, item.provision
                                )
                            ):
                                raise IdentityConflictError(
                                    "A provision ID cannot be reassigned "
                                    "to another stable key."
                                )

                        document_ids: dict[str, int] = {}
                        for document_name, document_writes in grouped.items():
                            ordered = sorted(
                                document_writes,
                                key=lambda value: (
                                    value.provision.sort_order,
                                    value.provision.provision_id,
                                ),
                            )
                            document_hash = canonical_json_hash(
                                [
                                    {
                                        "provision_id": item.provision.provision_id,
                                        "official_content_hash": (
                                            item.official_content_hash
                                        ),
                                    }
                                    for item in ordered
                                ]
                            )
                            source_url = next(
                                (
                                    item.provision.source_url
                                    for item in ordered
                                    if item.provision.source_url
                                ),
                                "",
                            )
                            await cursor.execute(
                                """
                                INSERT INTO legal_qa.legal_documents (
                                    document_name, canonical_document_name,
                                    source_url, official_content_hash, is_current,
                                    first_seen_run_id, last_seen_run_id
                                ) VALUES (%s, %s, %s, %s, true, %s, %s)
                                ON CONFLICT (document_name) DO UPDATE SET
                                    canonical_document_name =
                                        EXCLUDED.canonical_document_name,
                                    source_url = CASE
                                        WHEN EXCLUDED.source_url <> ''
                                        THEN EXCLUDED.source_url
                                        ELSE legal_qa.legal_documents.source_url
                                    END,
                                    official_content_hash =
                                        EXCLUDED.official_content_hash,
                                    is_current = true,
                                    last_seen_run_id = EXCLUDED.last_seen_run_id,
                                    updated_at = now()
                                RETURNING document_id
                                """,
                                (
                                    document_name,
                                    canonicalize_identity_text(document_name),
                                    source_url,
                                    document_hash,
                                    run.run_id,
                                    run.run_id,
                                ),
                            )
                            document_ids[document_name] = int(
                                (await cursor.fetchone())["document_id"]
                            )

                        for item in writes:
                            provision = item.provision
                            await cursor.execute(
                                """
                                INSERT INTO legal_qa.provision_identity_ledger (
                                    provision_id, canonical_stable_key,
                                    document_name, article_no, paragraph_no,
                                    subparagraph_no, identity_status,
                                    first_seen_run_id
                                ) VALUES (%s, %s, %s, %s, %s, %s, 'current', %s)
                                ON CONFLICT (provision_id) DO UPDATE SET
                                    canonical_stable_key =
                                        EXCLUDED.canonical_stable_key,
                                    document_name = EXCLUDED.document_name,
                                    article_no = EXCLUDED.article_no,
                                    paragraph_no = EXCLUDED.paragraph_no,
                                    subparagraph_no = EXCLUDED.subparagraph_no,
                                    identity_status = 'current',
                                    retired_run_id = NULL,
                                    updated_at = now()
                                """,
                                (
                                    provision.provision_id,
                                    item.canonical_stable_key,
                                    provision.document_name,
                                    provision.article_no,
                                    provision.paragraph_no,
                                    provision.subparagraph_no,
                                    run.run_id,
                                ),
                            )
                            await cursor.execute(
                                """
                                INSERT INTO legal_qa.legal_provisions (
                                    provision_id, document_id,
                                    canonical_stable_key, chapter_name,
                                    section_name, article_no, paragraph_no,
                                    subparagraph_no, title, content, search_text,
                                    search_compact, sort_order, source_url,
                                    official_content_hash, record_hash,
                                    embedding_input_hash, embedding_model,
                                    vector_collection, vector_generation,
                                    is_current, first_seen_run_id,
                                    last_seen_run_id
                                ) VALUES (
                                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                    %s, %s, true, %s, %s
                                )
                                ON CONFLICT (provision_id) DO UPDATE SET
                                    document_id = EXCLUDED.document_id,
                                    canonical_stable_key =
                                        EXCLUDED.canonical_stable_key,
                                    chapter_name = EXCLUDED.chapter_name,
                                    section_name = EXCLUDED.section_name,
                                    article_no = EXCLUDED.article_no,
                                    paragraph_no = EXCLUDED.paragraph_no,
                                    subparagraph_no = EXCLUDED.subparagraph_no,
                                    title = EXCLUDED.title,
                                    content = EXCLUDED.content,
                                    search_text = EXCLUDED.search_text,
                                    search_compact = EXCLUDED.search_compact,
                                    sort_order = EXCLUDED.sort_order,
                                    source_url = EXCLUDED.source_url,
                                    official_content_hash =
                                        EXCLUDED.official_content_hash,
                                    record_hash = EXCLUDED.record_hash,
                                    embedding_input_hash =
                                        EXCLUDED.embedding_input_hash,
                                    embedding_model = EXCLUDED.embedding_model,
                                    vector_collection = EXCLUDED.vector_collection,
                                    vector_generation = EXCLUDED.vector_generation,
                                    is_current = true,
                                    last_seen_run_id = EXCLUDED.last_seen_run_id,
                                    updated_at = now()
                                """,
                                (
                                    provision.provision_id,
                                    document_ids[provision.document_name],
                                    item.canonical_stable_key,
                                    provision.chapter_name,
                                    provision.section_name,
                                    provision.article_no,
                                    provision.paragraph_no,
                                    provision.subparagraph_no,
                                    provision.title,
                                    provision.content,
                                    provision.search_text,
                                    item.search_compact,
                                    provision.sort_order,
                                    provision.source_url,
                                    item.official_content_hash,
                                    item.record_hash,
                                    item.embedding_input_hash,
                                    run_row["embedding_model"],
                                    run_row["vector_collection"],
                                    item.vector_generation,
                                    run.run_id,
                                    run.run_id,
                                ),
                            )
                            await cursor.execute(
                                """
                                INSERT INTO legal_qa.legal_provision_versions (
                                    provision_id, record_hash,
                                    collection_run_id, document_name,
                                    article_no, official_content_hash,
                                    embedding_input_hash, record
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (provision_id, record_hash)
                                DO NOTHING
                                """,
                                (
                                    provision.provision_id,
                                    item.record_hash,
                                    run.run_id,
                                    provision.document_name,
                                    provision.article_no,
                                    item.official_content_hash,
                                    item.embedding_input_hash,
                                    Jsonb(provision.model_dump(mode="json")),
                                ),
                            )
                            await cursor.execute(
                                """
                                INSERT INTO legal_qa.collection_run_items (
                                    run_id, provision_id,
                                    embedding_input_hash, vector_action
                                ) VALUES (%s, %s, %s, %s)
                                """,
                                (
                                    run.run_id,
                                    provision.provision_id,
                                    item.embedding_input_hash,
                                    item.vector_action,
                                ),
                            )

                        deactivated: list[Mapping[str, Any]] = []
                        if full_snapshot:
                            await cursor.execute(
                                """
                                UPDATE legal_qa.legal_provisions
                                SET is_current = false,
                                    last_seen_run_id = %s,
                                    updated_at = now()
                                WHERE is_current
                                  AND NOT (provision_id = ANY(%s::bigint[]))
                                RETURNING provision_id, embedding_input_hash
                                """,
                                (run.run_id, ids),
                            )
                            deactivated = await cursor.fetchall()
                            deactivated_ids = [
                                int(row["provision_id"]) for row in deactivated
                            ]
                            if deactivated_ids:
                                await cursor.execute(
                                    """
                                    UPDATE legal_qa.provision_identity_ledger
                                    SET identity_status = 'retired',
                                        retired_run_id = %s,
                                        updated_at = now()
                                    WHERE provision_id = ANY(%s::bigint[])
                                    """,
                                    (run.run_id, deactivated_ids),
                                )
                                for row in deactivated:
                                    await cursor.execute(
                                        """
                                        INSERT INTO legal_qa.collection_run_items (
                                            run_id, provision_id,
                                            embedding_input_hash, vector_action
                                        ) VALUES (%s, %s, %s, 'deactivated')
                                        """,
                                        (
                                            run.run_id,
                                            row["provision_id"],
                                            row["embedding_input_hash"],
                                        ),
                                    )
                            await cursor.execute(
                                """
                                UPDATE legal_qa.legal_documents AS d
                                SET is_current = EXISTS (
                                        SELECT 1
                                        FROM legal_qa.legal_provisions AS p
                                        WHERE p.document_id = d.document_id
                                          AND p.is_current
                                    ),
                                    last_seen_run_id = %s,
                                    updated_at = now()
                                """,
                                (run.run_id,),
                            )

                        # A partial sync may contain only one provision from a
                        # document. Recompute each affected document hash from
                        # the complete current PostgreSQL snapshot so it never
                        # becomes a hash of the partial input by accident.
                        for document_id in document_ids.values():
                            await cursor.execute(
                                """
                                SELECT provision_id, official_content_hash
                                FROM legal_qa.legal_provisions
                                WHERE document_id = %s AND is_current
                                ORDER BY sort_order, provision_id
                                """,
                                (document_id,),
                            )
                            current_rows = await cursor.fetchall()
                            current_document_hash = canonical_json_hash(
                                [
                                    {
                                        "provision_id": int(row["provision_id"]),
                                        "official_content_hash": row[
                                            "official_content_hash"
                                        ],
                                    }
                                    for row in current_rows
                                ]
                            )
                            await cursor.execute(
                                """
                                UPDATE legal_qa.legal_documents
                                SET official_content_hash = %s,
                                    is_current = true,
                                    updated_at = now()
                                WHERE document_id = %s
                                """,
                                (current_document_hash, document_id),
                            )

                        await cursor.execute(
                            """
                            UPDATE legal_qa.collection_runs
                            SET status = 'succeeded',
                                deactivated_count = %s,
                                completed_at = now()
                            WHERE run_id = %s AND status = 'vector_staged'
                            """,
                            (len(deactivated), run.run_id),
                        )
                        if cursor.rowcount != 1:
                            raise RuntimeError("invalid collection run transition")
        except IdentityConflictError:
            raise
        except Exception as exc:
            raise _safe_database_error(exc) from None

        return PublishSummary(
            provision_count=len(writes),
            deactivated_ids=tuple(int(row["provision_id"]) for row in deactivated),
        )

    async def get_provisions_by_ids(
        self, provision_ids: Sequence[int]
    ) -> dict[int, ProvisionSnapshot]:
        """Fetch trusted current snapshots; caller order is not assumed."""

        if not provision_ids:
            return {}
        try:
            async with self._pool.connection() as connection:
                async with connection.cursor(row_factory=dict_row) as cursor:
                    await cursor.execute(
                        """
                        SELECT p.provision_id, d.document_name,
                               p.chapter_name, p.section_name, p.article_no,
                               p.paragraph_no, p.subparagraph_no, p.title,
                               p.content, p.search_text, p.sort_order,
                               p.source_url, p.is_current,
                               p.official_content_hash, p.record_hash,
                               p.embedding_input_hash, p.embedding_model,
                               p.vector_collection, p.vector_generation
                        FROM legal_qa.legal_provisions AS p
                        JOIN legal_qa.legal_documents AS d
                          ON d.document_id = p.document_id
                        WHERE p.provision_id = ANY(%s::bigint[])
                          AND p.is_current AND d.is_current
                        """,
                        (list(dict.fromkeys(provision_ids)),),
                    )
                    rows = await cursor.fetchall()
        except Exception as exc:
            raise _safe_database_error(exc) from None
        return {
            int(row["provision_id"]): ProvisionSnapshot(
                provision=_row_to_provision(row),
                official_content_hash=row["official_content_hash"],
                record_hash=row["record_hash"],
                embedding_input_hash=row["embedding_input_hash"],
                embedding_model=row["embedding_model"],
                vector_collection=row["vector_collection"],
                vector_generation=int(row["vector_generation"]),
            )
            for row in rows
        }

    async def keyword_candidates(
        self,
        *,
        compact_query: str,
        terms: Sequence[str],
        limit: int,
    ) -> list[ProvisionSnapshot]:
        """Return PG lexical candidates; Python owns the exact final score."""

        if limit <= 0:
            raise ValueError("limit must be positive")
        normalized_terms = list(dict.fromkeys(term for term in terms if term))
        if not compact_query and not normalized_terms:
            return []
        try:
            async with self._pool.connection() as connection:
                async with connection.cursor(row_factory=dict_row) as cursor:
                    await cursor.execute(
                        """
                        SELECT p.provision_id, d.document_name,
                               p.chapter_name, p.section_name, p.article_no,
                               p.paragraph_no, p.subparagraph_no, p.title,
                               p.content, p.search_text, p.sort_order,
                               p.source_url, p.is_current,
                               p.official_content_hash, p.record_hash,
                               p.embedding_input_hash, p.embedding_model,
                               p.vector_collection, p.vector_generation,
                               CASE
                                   WHEN %s <> '' AND strpos(
                                       p.search_compact, %s
                                   ) > 0 THEN 1
                                   ELSE 0
                               END AS phrase_hit,
                               (
                                   SELECT count(*)
                                   FROM unnest(%s::text[]) AS term(value)
                                   WHERE strpos(p.search_compact, term.value) > 0
                               ) AS matched_terms
                        FROM legal_qa.legal_provisions AS p
                        JOIN legal_qa.legal_documents AS d
                          ON d.document_id = p.document_id
                        WHERE p.is_current AND d.is_current
                          AND (
                              (%s <> '' AND strpos(
                                  p.search_compact, %s
                              ) > 0)
                              OR EXISTS (
                                  SELECT 1
                                  FROM unnest(%s::text[]) AS term(value)
                                  WHERE strpos(
                                      p.search_compact, term.value
                                  ) > 0
                              )
                          )
                        ORDER BY phrase_hit DESC, matched_terms DESC,
                                 p.sort_order, p.provision_id
                        LIMIT %s
                        """,
                        (
                            compact_query,
                            compact_query,
                            normalized_terms,
                            compact_query,
                            compact_query,
                            normalized_terms,
                            limit,
                        ),
                    )
                    rows = await cursor.fetchall()
        except Exception as exc:
            raise _safe_database_error(exc) from None
        return [
            ProvisionSnapshot(
                provision=_row_to_provision(row),
                official_content_hash=row["official_content_hash"],
                record_hash=row["record_hash"],
                embedding_input_hash=row["embedding_input_hash"],
                embedding_model=row["embedding_model"],
                vector_collection=row["vector_collection"],
                vector_generation=int(row["vector_generation"]),
            )
            for row in rows
        ]

    async def create_conversation(
        self, *, user_id: str | None = None, conversation_id: UUID | None = None
    ) -> UUID:
        conversation_id = conversation_id or uuid4()
        try:
            async with self._pool.connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO legal_qa.conversations (
                            conversation_id, user_id
                        ) VALUES (%s, %s)
                        ON CONFLICT (conversation_id) DO NOTHING
                        """,
                        (conversation_id, user_id),
                    )
                await connection.commit()
        except Exception as exc:
            raise _safe_database_error(exc) from None
        return conversation_id

    async def conversation_status(self, conversation_id: UUID) -> str | None:
        try:
            async with self._pool.connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT status
                        FROM legal_qa.conversations
                        WHERE conversation_id = %s
                        """,
                        (conversation_id,),
                    )
                    row = await cursor.fetchone()
        except Exception as exc:
            raise _safe_database_error(exc) from None
        return str(row[0]) if row else None

    async def append_message(
        self,
        conversation_id: UUID,
        *,
        role: Literal["user", "assistant", "system"],
        content: str,
        query_id: UUID | None = None,
    ) -> UUID:
        message_id = uuid4()
        try:
            async with self._pool.connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO legal_qa.messages (
                            message_id, conversation_id, role, content, query_id
                        ) VALUES (%s, %s, %s, %s, %s)
                        """,
                        (message_id, conversation_id, role, content, query_id),
                    )
                    await cursor.execute(
                        """
                        UPDATE legal_qa.conversations
                        SET updated_at = now()
                        WHERE conversation_id = %s
                        """,
                        (conversation_id,),
                    )
                await connection.commit()
        except Exception as exc:
            raise _safe_database_error(exc) from None
        return message_id

    async def recent_messages(
        self, conversation_id: UUID, *, limit: int
    ) -> list[dict[str, str]]:
        if limit <= 0:
            return []
        try:
            async with self._pool.connection() as connection:
                async with connection.cursor(row_factory=dict_row) as cursor:
                    await cursor.execute(
                        """
                        SELECT role, content
                        FROM (
                            SELECT role, content, created_at, message_id
                            FROM legal_qa.messages
                            WHERE conversation_id = %s
                            ORDER BY created_at DESC, message_id DESC
                            LIMIT %s
                        ) AS recent
                        ORDER BY created_at, message_id
                        """,
                        (conversation_id, limit),
                    )
                    rows = await cursor.fetchall()
        except Exception as exc:
            raise _safe_database_error(exc) from None
        return [
            {"role": str(row["role"]), "content": str(row["content"])} for row in rows
        ]

    async def start_qa_run(
        self,
        *,
        query_id: UUID,
        conversation_id: UUID | None,
        trace_id: str | None,
        profile_name: str,
        prompt_name: str,
        normalization_version: str,
        chat_model: str,
        embedding_model: str,
        vector_collection: str,
        question: str,
        normalized_question: str,
    ) -> None:
        try:
            async with self._pool.connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO legal_qa.qa_runs (
                            query_id, conversation_id, trace_id, profile_name,
                            prompt_name, normalization_version, chat_model,
                            embedding_model, vector_collection, question,
                            normalized_question, status
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            'running'
                        )
                        """,
                        (
                            query_id,
                            conversation_id,
                            trace_id,
                            profile_name,
                            prompt_name,
                            normalization_version,
                            chat_model,
                            embedding_model,
                            vector_collection,
                            question,
                            normalized_question,
                        ),
                    )
                await connection.commit()
        except Exception as exc:
            raise _safe_database_error(exc) from None

    async def finish_qa_run(
        self,
        query_id: UUID,
        *,
        response: Mapping[str, Any] | None,
        stage_latencies_ms: Mapping[str, int | float],
        error_category: str | None = None,
    ) -> None:
        status = "failed" if error_category else "succeeded"
        safe_error = None
        if error_category:
            safe_error = (
                "".join(
                    character
                    for character in error_category[:100]
                    if character.isalnum() or character in {"_", "-"}
                )
                or "unknown"
            )
        try:
            async with self._pool.connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE legal_qa.qa_runs
                        SET status = %s, response = %s,
                            stage_latencies_ms = %s,
                            error_category = %s, completed_at = now()
                        WHERE query_id = %s AND status = 'running'
                        """,
                        (
                            status,
                            Jsonb(dict(response)) if response is not None else None,
                            Jsonb(dict(stage_latencies_ms)),
                            safe_error,
                            query_id,
                        ),
                    )
                await connection.commit()
        except Exception as exc:
            raise _safe_database_error(exc) from None

    async def record_qa_retrievals(
        self,
        query_id: UUID,
        rows: Sequence[Mapping[str, Any]],
    ) -> None:
        if not rows:
            return
        values = [
            (
                query_id,
                row["rank"],
                row["provision_id"],
                row["vector_score"],
                row["keyword_score"],
                row["final_score"],
                row["official_content_hash"],
                row["record_hash"],
                row["embedding_input_hash"],
                row.get("excerpt_hash"),
            )
            for row in rows
        ]
        try:
            async with self._pool.connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.executemany(
                        """
                        INSERT INTO legal_qa.qa_retrievals (
                            query_id, rank, provision_id, vector_score,
                            keyword_score, final_score,
                            official_content_hash, record_hash,
                            embedding_input_hash, excerpt_hash
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (query_id, rank) DO UPDATE SET
                            provision_id = EXCLUDED.provision_id,
                            vector_score = EXCLUDED.vector_score,
                            keyword_score = EXCLUDED.keyword_score,
                            final_score = EXCLUDED.final_score,
                            official_content_hash =
                                EXCLUDED.official_content_hash,
                            record_hash = EXCLUDED.record_hash,
                            embedding_input_hash = EXCLUDED.embedding_input_hash,
                            excerpt_hash = EXCLUDED.excerpt_hash
                        """,
                        values,
                    )
                await connection.commit()
        except Exception as exc:
            raise _safe_database_error(exc) from None

    async def save_feedback(
        self,
        *,
        query_id: UUID,
        conversation_id: UUID | None,
        rating: int | None,
        category: str | None,
        comment: str | None,
    ) -> UUID:
        feedback_id = uuid4()
        try:
            async with self._pool.connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO legal_qa.feedback (
                            feedback_id, query_id, conversation_id,
                            rating, category, comment
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            feedback_id,
                            query_id,
                            conversation_id,
                            rating,
                            category,
                            comment,
                        ),
                    )
                await connection.commit()
        except Exception as exc:
            raise _safe_database_error(exc) from None
        return feedback_id


__all__ = [
    "PostgresRepository",
    "create_postgres_pool",
]
