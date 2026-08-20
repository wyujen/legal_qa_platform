# PostgreSQL 資料庫

PostgreSQL 是 application data 的 source of truth：法規 identity/current text、同步 runs、keyword searchable fields、QA runs/retrieval audit、conversation/messages與feedback。正式向量只在 Qdrant；migration 不建立 `vector` extension 或 pgvector column。

## Schema ownership

所有物件位於隔離的 `legal_qa` schema。Migration 必須 repeatable、non-destructive by default，只建立/修改此 schema 的物件；不得假設 superuser，也不得觸碰既有 LiteLLM tables。

Baseline migration 是 `migrations/0001_initial.sql`，由 `python scripts/migrate.py` 套用。若目前 application identity 無建 schema/物件權限，script 應回報所需權限/SQL action並停止，不要求 administrator credential。

## Table map

| Table | Purpose | Key invariants |
|---|---|---|
| `schema_migrations` | 已套用 migration versions | version唯一、可重跑 |
| `collection_runs` | full/partial sync lifecycle與generation | running/vector_staged/succeeded/failed；只有成功generation可讀 |
| `legal_documents` | 法規文件 master identity/current state | canonical name唯一，保存first/last run |
| `provision_identity_ledger` | stable ID ownership與退休保留 | ID不可回收或重綁；legacy reserved IDs不重用 |
| `legal_provisions` | current provision/search/hash/vector pointer | stable key、sort order、hash、generation、current狀態 |
| `legal_provision_versions` | master record歷史快照 | provision + record hash唯一 |
| `collection_run_items` | 每run各ID的vector action | upserted/reused/deactivated |
| `conversations` | application-owned對話 | UUID、active/closed |
| `messages` | ordered conversation turns | role/content/query relation |
| `qa_runs` | QA lifecycle/profile/model/latency/error | raw credential永不保存 |
| `qa_retrievals` | 每題ranked provisions與scores/hashes | query+rank與query+ID唯一 |
| `feedback` | rating/category/comment | 關聯query/conversation |

`provision_identity_ledger` 保留已退休 ID，讓從目前 active JSON 重建資料庫時也不會誤用歷史 ID。`legal_provisions.vector_collection/vector_generation/embedding_input_hash` 是和 Qdrant reconciliation 的 pointer，不是 vector storage。

## Keyword retrieval

`search_text` 保存可解釋的搜尋文字，`search_compact` 保存 canonical compact form；query先在 PostgreSQL選出 bounded candidates，再由 Python ranker計算同一套完整片語/bigram score。Baseline索引可從 prefix/一般 B-tree起步；資料量與 query plan需要時，可在不改 port的前提下新增正式 FTS/trigram migration。

不要把 keyword matching移到 Qdrant payload，也不要在 API endpoint內拼SQL。決策見 [ADR-0003](adr/0003-postgresql-keyword-retrieval.md)。

## Connection safety

Settings 分開 host/port/user/password/database並使用 redacting type保存密碼；DSN只在 PostgreSQL adapter邊界組合。禁止 log DSN、connection kwargs或database exception全文，因其可能含 credential/query values。Pool應有 bounded size、connect/query timeout與健康檢查；負載測試需區分 pool wait和 SQL latency。

Development/server分別使用 external/internal host，但同一 code path優先 internal。現有 `POSTGRES_LITELLM_*` identity僅是開發期既有credential，不代表production identity或admin權限。

## Transactions 與 cross-store consistency

單一 PostgreSQL operation使用 transaction；PostgreSQL與Qdrant不能共享transaction。同步run先記錄generation與預期狀態，向量stage/upsert後reconcile，最後才標記succeeded/current。QA只讀current row且其generation已成功。

若 Qdrant step失敗，PostgreSQL run標示failed/incomplete並保留上一個成功generation；重跑以hash和idempotent point ID收斂。不得為了回復一致性直接刪除所有master data。詳見 [ADR-0008](adr/0008-postgresql-qdrant-consistency.md)。

## Retention 未決事項

Conversation、question、answer、feedback可能含個資。正式retention、data deletion、student identity/SSO、audit與backup政策尚未授權；schema只提供能力，不自動決定期限或cascade policy。Production上線前由Human Operator/資料治理者確認，並以新migration實作。

## Verification

- Migration重跑不改變既有資料，schema version正確。
- Constraints拒絕stable ID重綁、非法status/role/rating與空正文。
- Repository unit/integration測current filter、deterministic order、keyword candidates與transactions。
- Reconciliation測PostgreSQL current IDs/hash/generation和Qdrant points一致。
- Live smoke只輸出connected/query passed/latency或安全error category，不輸出DSN、SQL parameter或credential。
