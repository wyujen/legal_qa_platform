# 法規同步與 Embedding

同步的目的，是把 repository 內已驗證的法規資料建立為 PostgreSQL master data，並讓 Qdrant 擁有同一批現行條文的 `bge-m3` 1024 維向量。流程必須可安全重跑、預設非破壞，且不依賴 reference repository。

## Input 與 output

正式 input 是本 repository 的 `data/legal_provisions.json`。`data/source_law.txt` 與 `data/collection_warnings.json` 是 provenance/audit 輔助，不可取代 validated provision contract。

每筆 provision 至少維持：

- stable `provision_id` 與 global `sort_order`；
- 法規名稱、條號、正文與結構欄位的既有語義；
- current/active 狀態；
- source metadata；
- canonical `content_hash` 與 `embedding_input_hash`。

Output 分成兩個 store：PostgreSQL 保存完整可稽核 master row 與 sync run；Qdrant 保存 vector、`provision_id` 與用於版本/一致性檢查的最少 payload。

## Validation gate

任何外部寫入前先在記憶體完成 strict validation：UTF-8/JSON/Pydantic schema、ID/sort order 唯一性、stable key ownership、必要正文、現行規則、duplicate policy 與完整/部分模式。資料不可摘要或改寫後才存為 master text。

治理規則：

- 已存在的 `provision_id` 不可靜默改綁其他 stable key。
- 法規改名視為新 document identity；不得用 fuzzy match 自動合併。
- 同名同正文可依既定規則去重；同名不同正文停止並交由人工判定。
- 只收現行正文。移除/停用必須留下 run provenance，而不是刪除歷史 identity。
- 正文中的正式內容必須納入 embedding input；hash 算法要 canonical、可重現並有測試。

## Hash 與重算判定

`content_hash` 代表 master content/metadata 的 canonical 狀態；`embedding_input_hash` 代表實際送入 embedding provider 的文字。向量可沿用，只有在下列條件全部相同時成立：

```text
provision_id identity
+ embedding_input_hash
+ embedding model name
+ embedding dimension
+ collection/vector version
```

任一項改變都須重新 embedding。Embedding 回應必須恰為 1024 個有限值且不是零向量；不合格時不可 upsert 或將 run 標為 succeeded。

## 同步演算法

1. 建立 `collection_run`，記錄 source fingerprint、mode、model/version 與開始時間。
2. 驗證整份 input，並與 PostgreSQL 既有 stable identity/hash 比較。
3. 分類 new、changed、unchanged；完整快照才另行計算 missing/deactivate。
4. 僅對 new/changed 的 embedding input 批次呼叫 LiteLLM `bge-m3`。
5. 以 stable point ID idempotently stage Qdrant points，payload帶hash/model/run generation；可沿用的vector只刷新非vector metadata。
6. PostgreSQL把run標成`vector_staged`，再於單一transaction upsert master/version/items、套用full-snapshot deactivation並publish succeeded/current generation。
7. Publish後best-effort把已停用ID的Qdrant payload標成非current；即使cleanup暫時失敗，retrieval仍以PostgreSQL current state拒絕它。
8. 比對expected IDs/counts/hashes完成reconciliation；失敗留下安全錯誤分類與可重試狀態。

PostgreSQL 與 Qdrant 沒有共同 transaction。正式策略與恢復原則見 [ADR-0008](adr/0008-postgresql-qdrant-consistency.md)。

## Full snapshot 與 partial sync

| Mode | Input 缺少既有 ID 的意義 | 可停用缺少資料 | 適用情況 |
|---|---|---|---|
| Full snapshot | 來源完整快照不再包含該條文 | 是，但只在整次驗證/寫入成功後 | 全量正式更新 |
| Partial sync | 此批次未包含，不代表已失效 | 否 | 單一法規修補、重試、小批更新 |

命令必須要求明確 mode，預設採 non-destructive partial 或 dry-run；不得因檔名或筆數猜測 full snapshot。

## Versioned Qdrant collection

Baseline 使用 `bge-m3` 與 cosine-compatible 1024 維 collection。Collection 名稱屬 replaceable configuration/ADR，而不是 domain constant；概念上可用 `legal_provisions_bge_m3_v1`。改模型或維度時建立新 collection/generation，完成驗證後切換 read alias，避免就地混合不同向量版本。

Point payload 應精簡且可追查：

```json
{
  "provision_id": 812,
  "document_name": "<DOCUMENT_NAME>",
  "article_no": "<ARTICLE_NO>",
  "official_content_hash": "<SHA256>",
  "record_hash": "<SHA256>",
  "embedding_input_hash": "<SHA256>",
  "embedding_model": "bge-m3",
  "is_current": true,
  "vector_generation": 42
}
```

法條正文與顯示 metadata 仍以 PostgreSQL 為準，不信任 Qdrant payload 作為 master copy。

## Repeatability 與 recovery

- 相同 input/model/version 重跑應得到 zero re-embedding、相同 active set 與相同 hash。
- Qdrant upsert 失敗後可依 run classification 重送相同 points，不需要回收 ID。
- Qdrant staged但PostgreSQL尚未publish時，payload/generation與current snapshot不符，retrieval必須拒絕；重跑可覆寫相同point ID。
- PostgreSQL publish後若Qdrant deactivation cleanup暫時失敗，current filter仍保證舊point不可用，並回報cleanup pending。
- Reconciliation 應能找出 missing point、unexpected point、hash mismatch 與 stale current flag。
- 清除舊 collection/version 是獨立、明確、需審核的維運動作，不屬同步預設行為。

## 如何測試

- Unit：canonical hash、stable identity、full/partial semantics、batch classification、維度/NaN/zero-vector rejection。
- Contract：同一份 JSON 的 provision count、ID、sort order 與 question-bank foreign key。
- Adapter integration：只在允許的 runtime variables 已注入時測 PostgreSQL/Qdrant/LiteLLM；輸出只列 service/status/dimension/latency。
- Recovery：故意讓第二個 store adapter 失敗，再驗證成功 generation 不變、重跑可收斂。
- Independence：任何 source/config/docs 不得引用 read-only reference repository 路徑。

Live 測試缺少 runtime configuration 時應安全 skip，交由 Human Operator 在已注入環境中執行；不得要求或接收 Secret。
