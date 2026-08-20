# PostgreSQL 資料庫

PostgreSQL 是 application data 的 source of truth：法規 identity/current text、同步 runs、keyword searchable fields、QA runs/retrieval audit、conversation/messages與feedback。正式向量只在 Qdrant；migration 不建立 `vector` extension 或 pgvector column。

## Schema ownership

所有物件位於隔離的 `legal_qa` schema。Migration 必須 repeatable、
non-destructive by default，只建立/修改此 schema 的物件，也不得觸碰
既有 LiteLLM tables。

Baseline migration 是 `migrations/0001_initial.sql`。`python scripts/migrate.py`
只是離線 bundle validator 與 DBeaver handoff；它不讀 environment、不連線，也不會
套用 migration。Human Operator 使用已自行管理的 DBeaver 連線執行 checked-in SQL。

`0001_initial.sql` 以 `BEGIN`/`COMMIT` 包住整份 DDL，採用 transaction-scoped advisory
lock，所有 schema objects 與 seed row 都是 repeatable forms。Migration version insert
固定在最後一個 statement；前面任一 statement 失敗時 transaction 不會寫入
`schema_migrations`。SQL 不含 role/user/database、placeholder、`GRANT` 或 `REVOKE`，
不會觸碰無關的 LiteLLM objects。

## DBeaver manual DDL workflow

1. 從 repository root 執行 `python scripts/migrate.py`。只接受
   `[PASS] offline migration bundle validated ... database_unchanged=true`；這一步不代表
   database 已套用。
2. 在 DBeaver 開啟 Human Operator 已建立的 PostgreSQL 管理連線。於 Database
   Navigator 與 SQL Editor toolbar 確認 active connection/catalog 是預定 application
   database；專案不提供或推測其名稱。
3. 使用 **SQL Editor → Open SQL Script** 開啟 repository 的
   `migrations/0001_initial.sql`，不要複製到其他未版本化檔案。
4. 使用 **Execute SQL Script** 執行整份檔案（DBeaver 預設通常為 `Alt+X`）；不要只用
   Execute SQL Statement/選取片段執行。
5. 確認執行沒有 error 且 transaction 到達 `COMMIT`。若失敗，先修正權限或目標選擇，
   再重跑同一份完整 SQL；不要手動插入 migration history。
6. Refresh `legal_qa` schema，開啟
   `migrations/checks/0001_initial_readonly.sql`，同樣以 Execute SQL Script 執行。
   這份 post-check 只讀 catalog/application tables；每個回傳 row 的 `passed` 都必須是
   `true`。
7. 以 DBeaver 的 role/object **Properties → Permissions/Privileges**（或平台既有 DBA
   管理流程）將下表能力授予預先存在的 runtime identity。不要把 identity 名稱寫入
   repository SQL。
8. 改用 runtime process 執行 `python scripts/smoke_test.py --phase dependencies`；通過後
   才執行 initial full sync。

Runtime identity 的 capability allowlist：

| Scope | Required capability |
| --- | --- |
| Target database | `CONNECT` |
| `legal_qa` schema | `USAGE`，沒有 `CREATE` |
| `collection_runs`, `legal_documents`, `provision_identity_ledger`, `legal_provisions`, `conversations`, `qa_runs` | `SELECT`, `INSERT`, `UPDATE` |
| `legal_provision_versions`, `collection_run_items`, `messages`, `qa_retrievals`, `feedback` | `SELECT`, `INSERT` |
| `legal_qa` sequences | `USAGE` only |
| `schema_migrations` | 無 runtime privilege |

不要授予 runtime identity `DELETE`、`TRUNCATE`、DDL、role/database administration、
schema ownership 或 default privileges。DBeaver 權限頁名稱可能依版本略有不同；能力
邊界以上表為準。專案不自動建立、修改或授權 identity。

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

Development/server分別使用 external/internal host，但同一 code path優先
internal。`POSTGRES_LITELLM_*` 是唯一由專案讀取的 PostgreSQL runtime identity，
只擁有 `legal_qa` 所需 DML、schema usage 與 sequence usage。DDL 使用 Human Operator
既有的 DBeaver 管理連線；專案不知道、讀取或保存該連線的 credential。

## Transactions 與 cross-store consistency

單一 PostgreSQL operation使用 transaction；PostgreSQL與Qdrant不能共享transaction。同步run先記錄generation與預期狀態，向量stage/upsert後reconcile，最後才標記succeeded/current。QA只讀current row且其generation已成功。

若 Qdrant step失敗，PostgreSQL run標示failed/incomplete並保留上一個成功generation；重跑以hash和idempotent point ID收斂。不得為了回復一致性直接刪除所有master data。詳見 [ADR-0008](adr/0008-postgresql-qdrant-consistency.md)。

## Retention 未決事項

Conversation、question、answer、feedback可能含個資。正式retention、data deletion、student identity/SSO、audit與backup政策尚未授權；schema只提供能力，不自動決定期限或cascade policy。Production上線前由Human Operator/資料治理者確認，並以新migration實作。

## Verification

- Migration重跑不改變既有資料，schema version正確。
- Offline validator確認transaction envelope、連續version、repeatable DDL/seed、最後才
  寫 migration history，並拒絕role/database/grant/destructive/placeholder SQL。
- DBeaver read-only post-check 的每個 `passed` row 都是 `true`。
- Runtime identity 可執行必要 CONNECT/schema usage/DML/sequence operation，
  但無 DDL 或其他 schema 權限。
- Constraints拒絕stable ID重綁、非法status/role/rating與空正文。
- Repository unit/integration測current filter、deterministic order、keyword candidates與transactions。
- Reconciliation測PostgreSQL current IDs/hash/generation和Qdrant points一致。
- Live smoke只輸出connected/query passed/latency或安全error category，不輸出DSN、SQL parameter或credential。
