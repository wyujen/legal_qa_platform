# Hybrid Retrieval

Baseline 的 retrieval 只有一份 Python ranking implementation：Qdrant 產生 semantic candidates，PostgreSQL 產生 explainable keyword candidates，service 以 stable `provision_id` 合併後計分、套 threshold，最後回傳可設定 Top K（baseline 為 6）。UI、API、CLI、evaluation 與 n8n 都不可複製另一套算法。

## Pipeline

```text
normalized question
├─ LiteLLM bge-m3 → 1024-d query vector → Qdrant candidate_k
└─ lexical normalization/terms → PostgreSQL candidate_k
                         ↓
              merge by provision_id
                         ↓
     vector_score + keyword_score normalization
                         ↓
 weighted hybrid score → min_score → stable sort → Top K
```

兩個 candidate source 的責任保持分離；目前流程先revalidate vector hits，再取得keyword candidates並為keyword-only IDs補齊Qdrant score。未來可在不改結果的前提下平行化部分I/O，但必須保留完整union rescoring與一致性檢查。任一critical retrieval dependency失效時回傳受控unavailable error，不靜默改成single-channel production answer。

## Question normalization

保留上一版已驗證行為：Unicode NFKC、基本標點/空白/英文大小寫統一，少量明確同義詞以一次取代處理，且不得改變條號中的數字或順序。Normalized text 用於 embedding 與 lexical matching；原始問題仍可保留於 API result/application log policy內。

Normalization 應是純函式，有 fixtures 覆蓋全形字、繁中標點、空白、條號、同義詞重疊與 empty input。

## Keyword signal

Keyword retrieval 不需要另一個 vector store。PostgreSQL 保存 `search_text`/canonical searchable fields，並以可索引的 query 找候選；Python 計算最終 lexical score。保留的透明規則包括：

- 完整 compact phrase 命中時得到最強 lexical signal。
- 英數 token 保持完整。
- 中文連續文字拆為 bigram。
- 明確低資訊問句詞不計入 term set。
- 條號 pattern（例如「第…條」）保留為可解釋 term。
- `keyword_score = matched query terms / all query terms`，無 terms 時為 0。

可搜尋欄位依序包含 document name、chapter/section、article number、title 與正文。PostgreSQL 只負責 candidate selection/master fetch；最終 score 仍由共用 ranker 決定。決策見 [ADR-0003](adr/0003-postgresql-keyword-retrieval.md)。

## Vector signal

Query embedding 固定由 LiteLLM `bge-m3` 產生，必須驗證 1024 維、有限且非零。Qdrant collection/version 必須與 ingestion 使用的 model/dimension/hash contract 相同，只搜尋 current/succeeded generation。

Qdrant 回傳 stable `provision_id` 與 vector score。顯示用正文、法規名稱與條號應回 PostgreSQL hydration，以 PostgreSQL master row 為準。選擇 Qdrant 而非 pgvector 見 [ADR-0002](adr/0002-qdrant-vector-store.md)。

## Merge 與 score

兩組 candidates 先各自 deduplicate/candidate-K，再以 `provision_id` union。Vector candidates 沿用 Qdrant search score；keyword-only IDs 必須回 Qdrant 驗證 payload，並以 `scores_for_ids` 取得同一 query vector 的 score。如此每個 production union member 都有兩個 components；缺少/stale vector 或 score 時 fail safe，不用 0 靜默降級。0 只允許在明確的 focused unit/degraded-path test 關閉 strict requirement 時使用。

Lexical component 不信任 candidate adapter 的暫存 score，會從 PostgreSQL-hydrated master provision 重新計算。Profile 要求兩個權重皆介於 0 與 1，且總和精確為 1：

```text
final_score = vector_weight * vector_score + keyword_weight * keyword_score
```

Baseline profile 概念值：candidate K 50、Top K 6、minimum score 0.12、vector weight 0.65、keyword weight 0.35、reranker disabled。實際值由 versioned RAG profile 提供，不散落於 endpoints。

排除 non-finite score 與非現行條文，套 minimum score，最後依 `final_score DESC, provision_id ASC` 做 deterministic sort，再取 Top K。每個 result 保留 vector、keyword 與 final score，方便 evaluation/troubleshooting。

## Context handoff contract

Retrieval output 至少包含：

```text
provision_id
document_name
article_no
title/content snapshot (from PostgreSQL)
source_url
content_hash
record_hash
embedding_input_hash
vector_score
keyword_score
final_score
rank
```

只有此 Top K 清單能形成本次 citation allowlist。Conversation messages、Qdrant payload 或 model 自己提到的 ID 均不得加入 allowlist。

## No reranker

Baseline 不呼叫已存在的 `bge-reranker-v2-m3`。先取得可重現的 hybrid/evaluation/load baseline，再以同一資料集與 profile metadata 做 on/off experiment。原因與重新評估條件見 [ADR-0004](adr/0004-baseline-without-reranker.md)。

## Failure modes 與測試

| Failure | Expected behavior | Test boundary |
|---|---|---|
| embedding 不是 1024 維/含非有限值 | adapter error，禁止搜尋 | embedding contract test |
| Qdrant collection/version 不合 | readiness/safe retrieval error | vector adapter integration |
| PostgreSQL keyword query 失敗 | safe retrieval error，不洩漏 DSN | repository integration |
| 同一 ID 兩邊 metadata 不同 | PostgreSQL hydration + consistency warning | merge unit/reconciliation test |
| invalid weights/K/threshold | profile validation fail fast | ranker unit test |
| equal score | provision ID deterministic tie-break | ranker unit test |
| 無達門檻結果 | typed no-result，不讓模型自由回答 | QA service test |

Evaluation 至少量測 expected provision hit/Recall@K、MRR（若實作）、candidate/Top K、各 signal score 與 latency。Expected answer/keywords/provision IDs 只供 evaluation，不得送入 production prompt。
