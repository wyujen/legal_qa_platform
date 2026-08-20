# Read-only Reference Migration Inventory

上一版 `legal-qa` 只在建置期作唯讀行為參考。`legal_qa_platform` 的code、data、test與runtime不得import、連結、讀取或依賴reference路徑；即使reference repository不存在，本專案仍須能clone、build、test、run與deploy。

## 保留

- `data/legal_provisions.json`：2,234筆、223部法規；stable IDs 9–2242、global sort order 1–2234。
- `data/qa_test_questions.json`：Q001–Q100共100題，expected values只供evaluation。
- `data/source_law.txt`與`data/collection_warnings.json`：作provenance/audit fixture；warning舊格式不直接當新domain schema。
- Stable `provision_id`/stable key、ID不回收、global `sort_order`與article/paragraph語義。
- 現行正文、完整vs部分同步、canonical content/embedding input hash、unchanged vector reuse。
- Question normalization、中文bigram/完整片語keyword score、vector+keyword hybrid、Top K、context extraction。
- Structured output、citation allowlist、local metadata overwrite、plain-text sanitization與固定notice。
- 高價值fixtures/tests：data contract、100題一致性、normalization、hybrid ranking、prompt/context、validation/citation、sync identity/hash與failure isolation。

## 重構

- 舊單體service拆為domain/service/adapter ports；framework type不進domain。
- SQL schema改為repeatable migrations與隔離`legal_qa` schema，加入generation、identity ledger、QA runs、conversation/messages/feedback。
- PostgreSQL adapter只做master/keyword/persistence；vector adapter改Qdrant。
- Embedding/chat adapter改LiteLLM REST的`bge-m3`/`campus-qa`，embedding固定1024維、chat必帶`max_tokens`。
- 同步改為PostgreSQL/Qdrant cross-store generation、idempotent upsert與reconciliation。
- JSONL QA log改PostgreSQL application records；Langfuse是best-effort trace。
- Streamlit保留為MVP操作面，但只呼叫REST API。
- Evaluation從舊Recall/MRR smoke擴充為retrieval hit、citation、validation、latency、profile/model/prompt metadata。

## 淘汰

- Ollama client/init/warmup/model volume。
- `embeddinggemma`與Gemma 4 runtime設定。
- PostgreSQL `vector(768)`、HNSW、`provision_embeddings` runtime storage。
- NPY embeddings、metadata/index與build flow。
- Streamlit直接import QA service。
- Redis、reranker、LangGraph、agents、自動法規收集、長期memory等非baseline能力。

## 已知資料/流程限制

- 正式snapshot的paragraph/subparagraph多為null，title/section多為空，長條文extraction主要依synthetic tests覆蓋。
- 有不同stable key但正文重複的records；不可因正文相同自動刪除或合併identity。
- 歷史warning未完整描述所有duplicate，且缺少新版預期的severity/context。
- Reference沒有可重現的自動collection script；checked-in data可作validated seed，但不可宣稱source collection pipeline已重建。
- Reference無Qdrant、LiteLLM、Langfuse或Kubernetes implementation，相關層為本專案重新設計。

## Independence verification

`python scripts/verify_repository.py`應掃描source、tests、scripts、config、docs與build metadata，拒絕reference絕對路徑、relative traversal、symlink/junction與runtime import依賴；也檢查禁止runtime identifiers（Ollama、pgvector/NPY正式flow等）和secret-safety patterns。檢查只讀本repository，不存取reference或任何Secret位置。
