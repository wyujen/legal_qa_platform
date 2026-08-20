# Legal QA Platform v2 — Codex 全面實作與架構 Brief

> 文件用途：作為 Legal QA Platform v2 重構期間，提供給 Codex 的長期專案背景、架構邊界、實作原則與階段任務。
>
> 參考來源：上一版 MVP README、現有 AI／RAG 平台資源盤查、目前允許的開發環境變數清單。
>
> 重要：本版本採 **Codex 全面實作模式**。Codex 可以自主建立完整 Platform v2 架構、實作、整合、測試、Docker、部署文件與必要工具，不需要逐步停下等待開發者手動輸入。完成後，開發者會再依架構文件、資料流與實際程式逐層理解整套系統，因此 Codex 必須把「可理解性、可追蹤性、可替換性、可測試性」視為一級需求。

---
## 本機開發專案與上一版參考專案路徑

目前 Legal QA Platform 的正式開發專案固定使用以下路徑：

```text
C:\Users\wyujen.SD\code\test\legal_qa_platform
```

上一版 Legal QA MVP 專案位於：

```text
C:\Users\wyujen.SD\code\sample\legal-qa
```

兩個專案的角色必須明確區分。

### 目前正式開發專案

```text
C:\Users\wyujen.SD\code\test\legal_qa_platform
```

此目錄為目前正式開發中的 `legal_qa_platform` 專案，也是 Codex 的主要開發 workspace。

所有新的：

* Application architecture
* Python source code
* REST API
* PostgreSQL schema / migration
* Qdrant integration
* LiteLLM integration
* Langfuse integration
* Retrieval / RAG implementation
* Tests
* Docker
* Kubernetes templates
* Documentation
* Scripts
* Configuration templates

都必須建立或修改於此專案。

專案名稱統一為：

```text
legal_qa_platform
```

不得自行使用：

```text
legal-qa-platform-v2
legal_qa_platform_v2
Platform v2
```

等名稱作為 repository、package、Docker image、路徑或正式文件名稱，除非 Human Operator 之後另外指定。

---

### 上一版 MVP 參考專案

```text
C:\Users\wyujen.SD\code\sample\legal-qa
```

此目錄只作為上一版 MVP 的 reference / source。

Codex 可以讀取此專案，以理解、比較及搬移上一版已驗證的設計，包括但不限於：

```text
data/legal_provisions.json
data/qa_test_questions.json

Pydantic schema
LegalProvision schema
LegalQaResult schema

Prompt
Structured Output
Citation allowlist
Citation validation

Question normalization
Vector retrieval
Keyword retrieval
Hybrid ranking
Top K
Context extraction

資料同步規則
content hash
provision_id 穩定性規則
現行法規判定規則

100 題 evaluation dataset
既有 unit / integration tests
README
architecture / data flow
既有 QA 執行流程
```

上一版 MVP 的主要價值是：

```text
資料
Schema
Domain rules
已驗證流程
測試資料
既有行為
```

而不是要求新專案保留上一版所有 infrastructure implementation。

上一版包含的：

```text
Ollama
embeddinggemma
gemma4:e2b-it-qat
PostgreSQL pgvector runtime
舊 provision_embeddings implementation
NPY embedding 流程
舊 Compose infrastructure
```

可以作為理解與比較來源，但不得因為「上一版這樣做」而直接限制新專案架構。

---

### Codex 對上一版專案的操作限制

Codex 可以：

```text
讀取上一版 source code
讀取上一版 JSON
讀取 schema
讀取 tests
讀取 README / docs
比較新舊流程
搬移需要保留的資料
重新實作已驗證的 domain logic
```

Codex 不得直接修改：

```text
C:\Users\wyujen.SD\code\sample\legal-qa
```

上一版專案應視為：

```text
read-only reference
```

所有正式修改都必須發生於：

```text
C:\Users\wyujen.SD\code\test\legal_qa_platform
```

---

### 搬移上一版內容的原則

如果需要沿用上一版的：

```text
JSON
Schema
Prompt
Tests
Domain logic
Retrieval algorithm
Validation rule
Evaluation dataset
```

Codex 應先理解其用途及相依關係，再：

```text
複製
重構
重新實作
```

到目前的：

```text
legal_qa_platform
```

不得讓新專案在 runtime 直接依賴上一版專案路徑。

例如不得出現：

```python
open(
    r"C:\Users\wyujen.SD\code\sample\legal-qa\data\legal_provisions.json"
)
```

不得使用：

```text
..\..\sample\legal-qa\data\...
```

也不得透過：

```text
symbolic link
junction
直接 Python import
PYTHONPATH
runtime file reference
```

讓新專案依賴上一版 Repository。

上一版資料若為新專案 runtime 所需要，必須正式存在於：

```text
legal_qa_platform
```

自己的專案結構內。

---

### 新版專案獨立性要求

`legal_qa_platform` 必須是一個完整且獨立的 Repository。

完成後，即使：

```text
C:\Users\wyujen.SD\code\sample\legal-qa
```

完全不存在，新專案仍然必須能正常：

```text
clone
install
build
unit test
integration test
run
Docker build
Docker run
deploy
```

也就是：

```text
legal_qa_platform
```

不得對上一版 repository 存在任何 runtime dependency。

上一版只是一個開發期間的：

```text
reference implementation
```

不是新系統的：

```text
dependency
submodule
runtime source
shared data directory
```

---

### Codex 的工作目錄

Codex 的主要工作目錄固定為：

```text
C:\Users\wyujen.SD\code\test\legal_qa_platform
```

除非 Human Operator 明確要求，Codex 不應在此路徑以外建立新的 Legal QA application source code。

如果需要參考上一版，可以讀取：

```text
C:\Users\wyujen.SD\code\sample\legal-qa
```

但完成分析後，正式成果必須寫回：

```text
C:\Users\wyujen.SD\code\test\legal_qa_platform
```

---

### Secret 與其他外部資料

上述兩個專案路徑都不代表 Codex 可以搜尋其他相鄰目錄。

Codex 不得因為知道：

```text
C:\Users\wyujen.SD\code\
```

而自行探索：

```text
secure
credentials
secret
其他 repository
使用者 home 目錄
PowerShell profile
environment loading script
其他未明確授權的路徑
```

Codex 的可知範圍應限制為：

```text
目前 legal_qa_platform Repository

以及

Human Operator 明確指定可作為 reference 的上一版 legal-qa Repository
```

其他位置不屬於開發上下文。

---

### 最終目標

開發期間的關係為：

```text
上一版 MVP
C:\Users\wyujen.SD\code\sample\legal-qa
          │
          │ reference only
          ▼
目前正式專案
C:\Users\wyujen.SD\code\test\legal_qa_platform
          │
          ▼
     build / test
          │
          ▼
        Docker
          │
          ▼
 Server / Kubernetes
```

正式完成後：

```text
legal_qa_platform
```

必須能完全脫離：

```text
legal-qa
```

而獨立運作。
---

## 1. 專案目標

目前已有一套可運作的「本機多法規 AI QA MVP」。上一版由 Codex 幾乎完整實作，因此雖然功能已跑通，但開發者對內部每一層的資料流、抽象、錯誤處理與維護點不夠熟悉。

v2 的目標不是延續上一版的 infrastructure implementation，而是：

1. 保留上一版已驗證的資料格式、Pydantic schema、法規資料、測試題庫與主要 RAG 行為。
2. 以新的平台既有資源重新建立一套乾淨的 RAG Application Core。
3. v2 由 Codex 先完整建立可執行架構與主要實作；完成後再由開發者逐層理解、驗證與接手維護。
4. 目前先做平台上的內部 MVP，但架構必須能自然延伸至未來正式學生服務。
5. 未來要支援多人同時使用、對話上下文、內外部模型、REST API、Docker、Kubernetes 與負載測試。
6. Framework 可以使用，但不能讓整個產品被單一 Framework 綁死。

---

## 2. 開發合作原則（Codex 必須遵守）

這是本專案最重要的協作規則。

### 2.1 Codex 可以完整建立整套 Platform v2

本版本不要求逐 Phase 停下等待開發者手動實作。

Codex 可以自主完成：

```text
project skeleton
Domain / Service / Adapter architecture
PostgreSQL schema / repository
Qdrant collection / ingestion / retrieval
LiteLLM embedding / chat adapters
Hybrid retrieval
Context Builder
Prompt / Structured Output
Citation Validation
Langfuse tracing
REST Application API
Streamlit 測試 UI
Docker
測試
100 題 evaluation
server / Kubernetes 部署範本
load test 工具
README 與 architecture documents
```

若當前 repository 已有可沿用的 code / schema / data，優先重用已驗證資產，不要為了重寫而重寫。

### 2.2 完成度優先，但禁止做成「只有 Codex 看得懂」

Codex 可以一次完成大量工作，但每個重要模組必須具備清楚邊界。

至少要讓開發者能回答：

1. 這個 module 解決什麼問題？
2. Input / Output 是什麼？
3. 它依賴哪些外部服務？
4. 哪些設定可以調？
5. 哪些錯誤可能發生？
6. 壞掉時從哪個 log / trace / test 開始查？
7. 如果未來替換 Qdrant、LiteLLM、Langfuse 或 Framework，哪一層需要改？

不要把多個責任塞進單一巨大 service、utility 或 workflow。

### 2.3 必須主動產生「理解用文件」

除了 README，至少建立：

```text
docs/
├─ architecture.md
├─ data_flow.md
├─ ingestion.md
├─ retrieval.md
├─ context_and_prompt.md
├─ model_gateway.md
├─ observability.md
├─ database.md
├─ api.md
├─ testing.md
├─ deployment.md
├─ configuration.md
├─ security_and_secrets.md
├─ load_testing.md
└─ troubleshooting.md
```

如果實際架構不需要其中某一份，可合併，但文件涵蓋的主題不可消失。

另外建立：

```text
docs/adr/
```

用 ADR（Architecture Decision Record）記錄會影響未來維護的重要決策，例如：

```text
為什麼使用 Qdrant 而不是 pgvector
為什麼 PostgreSQL 仍保留 keyword retrieval
為什麼第一版不用 reranker
為什麼 Langfuse 是 observability 而不是 hard dependency
為什麼 n8n 不持有唯一 production RAG domain logic
Application REST API 使用哪個 framework 及其替換邊界
Conversation source of truth 放在哪裡
```

### 2.4 保留可追蹤的實作歷程

即使 Codex 一次完成整體，也應按合理里程碑整理工作，不要產生難以 review 的混亂修改。

若環境允許 Git commit，可採概念上的拆分：

```text
chore: initialize platform v2 structure
feat: preserve legal data contracts
feat: add litellm embedding adapter
feat: add qdrant ingestion and retrieval
feat: add postgres keyword retrieval
feat: add hybrid ranking and context builder
feat: add campus qa generation and validation
feat: add langfuse observability
feat: add rest api and streamlit client
feat: add evaluation and load testing
chore: add docker and kubernetes deployment
 docs: add architecture and operations guides
```

不要為了 commit 數量硬拆；重點是之後可以追查架構演進。

### 2.5 測試是完整實作的一部分，不是最後補件

Codex 必須同時建立：

```text
unit tests
integration tests
evaluation tests / scripts
health / readiness checks
load test scenario
```

每個核心模組應有獨立驗證能力，避免只能靠 Streamlit 手動點擊確認。

### 2.6 不要過度 Framework 化

可以使用成熟 Framework / SDK，但必須遵守：

```text
Application Architecture != LangChain Architecture
Application Architecture != LangGraph Architecture
Application Architecture != n8n Workflow
```

Domain / Service contract 必須屬於本專案。

Framework 是 implementation dependency；若未來替換 Framework，不應重寫整個法規 QA domain logic。

### 2.7 遇到未決事項時的處理方式

Codex 不需要因為每個小決策停下等待確認。

如果某項未決事項不會造成不可逆結果，可以：

1. 選擇最保守、最容易替換的 MVP 預設值。
2. 把假設寫進 ADR / config / README。
3. 避免把假設寫死進 domain model。

只有在以下情況才應停止並要求決策：

```text
可能破壞既有法規資料
可能遺失 production data
需要真實 secret / credential
涉及不可逆資料 migration
會明顯改變既定 RAG 行為
涉及安全 / 身分驗證 / 個資政策
需要對外正式網域或正式 production routing
```

### 2.8 Build Phase 完成後要能直接進入 Understand Phase

Codex 的交付不只要「能跑」，還要讓後續可以照以下順序教學：

```text
1. 一個 request 從 UI 到 answer 的完整資料流
2. Data / Schema
3. Ingestion / Embedding
4. Qdrant Vector Retrieval
5. PostgreSQL Keyword Retrieval
6. Hybrid Ranking
7. Context Builder
8. Prompt / Model Gateway
9. Structured Output / Citation Validation
10. Conversation Context
11. Langfuse Trace
12. REST API
13. Docker / Kubernetes
14. Tests / Evaluation
15. Load / Concurrency
16. Troubleshooting
```

因此重要程式不要依賴隱晦 magic、動態 monkey patch 或沒有文件的隱性行為。

# 3. 上一版 MVP 已有內容

上一版是完全本機的繁體中文法規 QA MVP。

主要組成：

```text
回答模型：gemma4:e2b-it-qat
Embedding：embeddinggemma
Vector DB：PostgreSQL + pgvector
UI：Streamlit
Schema / response validation：Pydantic
```

主要 QA 流程：

```text
問題正規化
  ↓
embeddinggemma 產生問題向量
  ↓
pgvector HNSW 向量候選
  +
PostgreSQL 中文 bigram / 完整片語候選
  ↓
Python Hybrid Score
  ↓
Top 6
  ↓
長條文相關段落擷取
  ↓
防注入 Prompt + Pydantic JSON Schema
  ↓
Gemma 4
  ↓
Structured Output 驗證
  ↓
Citation allowlist
  ↓
Streamlit 顯示回答與引用
  ↓
QA log / user feedback
```

目前資料大約為：

- 223 部法規。
- 2,234 筆條文。
- 100 題 QA 測試題庫。

---

# 4. v2 要保留的資產

v2 不等於全部重做。

## 4.1 必須保留

### Data

```text
data/legal_provisions.json
data/qa_test_questions.json
```

其他 staging / 稽核資料依需要保留：

```text
data/source_law.txt
data/collection_warnings.json
```

### Schema / Domain Model

盡量沿用上一版已驗證的 Pydantic / JSON schema，例如：

```text
LegalDocument
LegalProvision
LegalQaResult
Citation
QuestionBankItem
```

實際名稱以原專案為準，不要自行改 schema 意義。

### 法規資料治理規則

保留：

- `provision_id` 穩定。
- `sort_order` 全域規則。
- `article_no` 規則。
- 同一 provision ID 不得偷偷改配其他條文。
- 正式正文納入 Embedding input。
- 只收現行正文。
- 不摘要、不改寫來源正文。
- 法規改名視為新文件。
- 同名同正文去重。
- 同名不同正文停止並人工判定。
- 完整快照與部分同步要區分。
- content / embedding input hash 用於判斷向量是否需要重建。

### QA / Retrieval 行為

第一版 platform MVP 仍保留：

```text
Vector Retrieval
+
Keyword Retrieval
→ Hybrid Score
→ Top K（目前 6）
→ Context extraction
→ Prompt
→ Structured output
→ Citation validation
```

### 題庫

保留 100 題：

```text
question
expected_answer
expected_keywords
expected_provision_ids
document_name
article_no
```

這些 expected values 只用於 evaluation，不送進 production model prompt。

---

# 5. v2 不保留 / 要替換的上一版 implementation

以下是舊 infrastructure 的 implementation，不應成為 v2 架構包袱。

## 5.1 移除 / 停止作為正式 runtime

```text
Ollama adapter
embeddinggemma runtime
Gemma 4 runtime
PostgreSQL pgvector runtime retrieval
provision_embeddings 作為正式 vector storage
舊 NPY embedding 流程
build_embeddings.py
embedding_metadata.json
Ollama init / warmup Compose services
Streamlit 直接 import QAService 的緊耦合方式
```

舊工具可暫時保留在 legacy / reference，但 v2 runtime 不依賴。

---

# 6. 現有 AI / RAG 平台資源

目前 server 上已存在共用 AI infrastructure。

## 6.1 PostgreSQL

```text
PostgreSQL 16.14
Image: pgvector/pgvector:pg16
StatefulSet: 1 replica
Storage: Synology CSI iSCSI retain 10 GiB
```

目前有：

```text
postgres database
litellm database
```

法規 RAG application 必須建立自己的 database / schema，不要把資料混進 LiteLLM database。

v2 第一版預計 PostgreSQL 負責：

```text
legal_documents
legal_provisions
collection_runs
keyword retrieval
未來 conversations
未來 messages
未來 feedback
其他 application metadata
```

**正式 vector 不再放 PostgreSQL。**

## 6.2 Qdrant

現有：

```text
Qdrant v1.18.2
3 replicas
cluster consensus 正常
HTTP / gRPC / P2P
api-key 驗證
每 replica 10 GiB PVC
目前 collection 為空
```

v2 正式 Embedding / Vector Retrieval 使用 Qdrant。

第一個 Embedding collection 應使用 `bge-m3` 1024 維向量。

Collection 名稱不要隨便硬編碼，應可版本化，例如概念：

```text
legal_provisions_bge_m3_v1
```

最終命名仍可討論。

## 6.3 LiteLLM

平台現有 LiteLLM Gateway。

目前已公開模型：

```text
campus-qa
bge-m3
bge-reranker-v2-m3
```

Smoke test 已確認：

```text
/v1/chat/completions → HTTP 200
/v1/embeddings       → HTTP 200，1024 維
/v1/rerank           → HTTP 200
/health/readiness    → healthy
```

注意：

`campus-qa` chat request 目前必須明確帶 `max_tokens`，否則底層 Xinference llama.cpp adapter 可能回 HTTP 500。

目前 Virtual Key 限制：

```text
60 RPM
100000 TPM
5 parallel
```

因此未來 load test 必須區分：

```text
Application concurrency
vs
Model inference concurrency / gateway quota
```

## 6.4 Redis Cluster

現有：

```text
Redis 7.0.15
3 leader + 3 follower
cluster_state: ok
```

目前 Platform MVP **先不用**。

未來正式學生版可能用途：

```text
rate limit
hot session cache
conversation cache
distributed lock
temporary state
```

Redis 不作永久 conversation source of truth。

---

# 7. 已確定的模型方向

Platform MVP 第一版：

```text
Chat Model: campus-qa
Embedding Model: bge-m3
Reranker: 先不用
```

上一版 embeddinggemma 為 768 維。

新平台 `bge-m3` 為 1024 維，因此：

> 所有正式條文都要重新使用 bge-m3 產生 Embedding。

不沿用上一版向量。

Reranker `bge-reranker-v2-m3` 已存在，但先保留作為後續 RAG Experiment，不放入第一個 baseline。

---

# 8. 終局產品需求

目前是內部 MVP，但設計不能只服務內部測試。

確定的長期方向：

1. 未來要提供學生使用。
2. 多人可以同時提問。
3. 支援多輪 Conversation Context。
4. 同時存在：
   - 內部模型。
   - 外部模型。
5. 模型以 RESTful API 方式提供，不限定模型 server 使用 FastAPI。
6. Model implementation 可能是：
   - Xinference。
   - vLLM。
   - Ollama。
   - 自建 inference server。
   - OpenAI / Gemini / Claude 等外部服務。
7. Application 不應依賴模型底層實作。
8. App 要 Docker 化。
9. Server 要可部署於 Kubernetes。
10. 要能進行 concurrency / load test。
11. 未來內容不限於目前法規 MVP，可能增加其他 AI workflow / knowledge source。

---

# 9. 核心架構原則

## 9.1 AI 核心 Python 化

不是所有服務自己用 Python 重寫。

Python 主要負責：

```text
RAG Application Core
Domain Logic
Adapters
Validation
Evaluation
```

不重寫：

```text
PostgreSQL
Qdrant
LiteLLM
Langfuse
n8n
Redis
模型 inference server
```

## 9.2 系統服務化

外部 infrastructure 都透過正式 client / REST API 使用。

概念：

```text
Python RAG Core
├─ PostgreSQL
├─ Qdrant
├─ LiteLLM REST
└─ Langfuse
```

## 9.3 模型全部經統一 Gateway / Adapter

RAG Application 不應散落：

```text
campus-qa URL
Gemini URL
OpenAI URL
其他 model URL
```

Application Core 只認抽象能力，例如：

```text
chat()
embed()
rerank()
```

目前 implementation：

```text
ChatModel       → LiteLLM → campus-qa
EmbeddingModel  → LiteLLM → bge-m3
Reranker        → 未啟用
```

未來可換 implementation，而不修改 QA domain logic。

## 9.4 Framework 只是 implementation dependency

不要形成：

```text
Application Architecture == LangChain Architecture
```

或：

```text
Application Architecture == n8n Workflow
```

自己的 Domain / Service interface 必須存在。

例如概念：

```python
class ChatModel:
    async def chat(...): ...

class EmbeddingProvider:
    async def embed(...): ...

class VectorStore:
    async def search(...): ...
```

實際 interface 細節在實作時逐步決定。

---

# 10. Framework 決策

## 10.1 Langfuse — Day 1 導入

確定導入。

用途：

```text
Tracing
Prompt Management
Dataset
Experiments
Evaluation
```

第一版希望一個 QA Trace 可看到：

```text
question
│
├─ normalize
├─ embedding
├─ vector_retrieval
├─ keyword_retrieval
├─ hybrid_ranking
├─ context_build
├─ generation
├─ response_validation
└─ citation_validation
```

每一個重要 span 至少考慮紀錄：

```text
latency
model
prompt version
retrieval parameters
Top K
provision IDs
scores
validation result
```

重要：

> Langfuse 掛掉時，QA production path 原則上仍應可正常服務。

Observability 不要變成核心 hard dependency。

## 10.2 LangChain — 可以使用，但採 Thin LangChain

LangChain 不排除，但第一個 milestone 不急著導入。

開發者必須至少親自走過一次：

```text
REST model call
REST embedding call
Qdrant search
PostgreSQL query
Hybrid ranking
Prompt build
Pydantic validation
```

理解底層後，再選擇哪些 boilerplate 交給 LangChain。

適合 LangChain 幫忙的可能範圍：

```text
model abstraction
document abstraction
prompt components
Qdrant integration
structured output helper
```

不應直接把 domain logic 全部藏入黑盒 RetrievalQA chain。

## 10.3 LangGraph — 第一版先不用

未來如果出現明確：

```text
branch
loop
retry
agent
human-in-the-loop
stateful long-running workflow
```

再評估加入。

目前 deterministic RAG pipeline 不需要為了 Framework 而增加 Graph complexity。

## 10.4 n8n — AI Lab / Workflow Tool

n8n 可以使用，而且很適合視覺化調整與內部 AI workflow。

適合：

```text
Batch evaluation
100 題 experiment
Prompt / Profile orchestration
模型 smoke test
法規 ingestion workflow
排程
通知
管理流程
```

不建議把唯一的 RAG domain logic 全部放進 n8n。

原因：

1. Production code 的 unit / integration test 更自然。
2. Git / PR / CI/CD 更自然。
3. 複雜 Workflow 最後可能變成大量 node / expression / Code Node。
4. 未來如果不使用 n8n，正式學生服務仍可保留。
5. 授權與產品邊界未來仍應依實際正式部署模式確認。

理想關係：

```text
n8n AI Lab
    ↓ REST
RAG Application API
```

而不是：

```text
學生 production request
    ↓
只有 n8n 裡才存在的 domain logic
```

---

# 11. Platform MVP 目標資料流

第一版先維持上一版主要行為，只替換 infrastructure。

```text
Question
   ↓
Normalize
   ↓
LiteLLM / bge-m3
   ↓
1024-d query vector
   ↓
Qdrant Vector Retrieval
         +
PostgreSQL Keyword Retrieval
         ↓
Hybrid Ranker
         ↓
Top 6
         ↓
Context Extraction
         ↓
Prompt
         ↓
LiteLLM / campus-qa
         ↓
Structured Output
         ↓
Pydantic Validation
         ↓
Citation Allowlist
         ↓
Answer
```

第一版明確不加入：

```text
Reranker
Agent
LangGraph
Redis runtime
Long-term memory
自動法規更新
```

目的是先建立可比較的 Platform Baseline。

---

# 12. 資料儲存責任

## PostgreSQL

Source of truth / Application data：

```text
legal_documents
legal_provisions
collection_runs
keyword retrieval
```

未來增加：

```text
conversations
messages
feedback
user mapping / application metadata
```

## Qdrant

只負責 Vector Search / vector metadata。

概念 point：

```json
{
  "id": 812,
  "vector": ["1024 dimensions"],
  "payload": {
    "provision_id": 812,
    "document_name": "...",
    "article_no": "...",
    "content_hash": "...",
    "is_current": true,
    "embedding_model": "bge-m3"
  }
}
```

優先考慮讓 Qdrant point ID 與 `provision_id` 對應，方便：

```text
Question Bank expected_provision_ids
↕
PostgreSQL legal_provisions
↕
Qdrant points
↕
Langfuse traces
```

是否完全一對一仍可在實作時確認。

---

# 13. Embedding / 法規同步設計

v2 重寫同步流程，不直接修改舊 pgvector 同步器。

目標：

```text
legal_provisions.json
        ↓
Pydantic / schema validation
        ↓
PostgreSQL master data upsert
        ↓
content / embedding input hash compare
        ↓
需要重新 embedding？
    ┌────────┴────────┐
    no               yes
    │                 ↓
    │           LiteLLM bge-m3
    │                 ↓
    │             1024 vector
    │                 ↓
    └──────────→ Qdrant upsert
```

必須保留：

- unchanged provision 不重算 embedding。
- changed provision 不得繼續使用舊 vector。
- embedding model 改變時必須可建立新的 collection / vector version。
- full snapshot 和 partial sync 的語意不可混淆。

---

# 14. RAG Profile — 從第一版就 Profile 化

不要把 AI 實驗參數散落在 Python code。

概念 model：

```python
class RagProfile(BaseModel):
    name: str
    chat_model: str
    embedding_model: str
    candidate_k: int = 50
    top_k: int = 6
    min_score: float = 0.12
    vector_weight: float = 0.65
    keyword_weight: float = 0.35
    reranker_enabled: bool = False
    prompt_name: str
```

概念 profile：

```json
{
  "name": "baseline-platform-v1",
  "chat_model": "campus-qa",
  "embedding_model": "bge-m3",
  "candidate_k": 50,
  "top_k": 6,
  "min_score": 0.12,
  "vector_weight": 0.65,
  "keyword_weight": 0.35,
  "reranker_enabled": false,
  "prompt_name": "legal-qa-v1"
}
```

未來這個 Profile 可以被：

```text
Streamlit
n8n
CLI
Langfuse Experiment
管理 UI
```

共同使用。

目標是讓：

> 實驗參數可調，但正式演算法 implementation 仍然只有一份。

---

# 15. Conversation Context 設計原則

Platform MVP 可先不做完整 memory，但 API / schema 要從一開始預留 conversation identity。

概念：

```text
conversation
------------
id
user_id
created_at
updated_at

message
-------
id
conversation_id
role
content
created_at
```

第一階段可以只使用：

```text
最近 N 則訊息
+
本次 RAG Context
```

未來才增加：

```text
summary memory
long-term memory
semantic memory
token budgeting
```

要清楚區分：

```text
Conversation Context
```

與：

```text
RAG Context
```

永久聊天資料應由 Application DB 控制，不要讓 LangChain / LangGraph / n8n memory 成為唯一資料來源。

---

# 16. REST API 原則

模型是 RESTful API，不代表模型一定用 FastAPI。

同樣地，學生 Application API 的 framework 目前也不是已確定事項。

可能為：

```text
Python FastAPI
ASP.NET Core Web API
其他 REST backend
```

目前最重要的是 Application Core 與 REST interface 分離。

未來 API 概念：

```text
POST /api/v1/chat
POST /api/v1/retrieve
POST /api/v1/feedback
POST /api/v1/experiments/run
GET  /health
GET  /ready
```

Chat request 從第一版就應考慮：

```json
{
  "conversation_id": "...",
  "message": "...",
  "profile": "baseline-platform-v1"
}
```

實際 schema 在實作階段再逐步確認。

Streamlit Platform MVP 最終應改成：

```text
Streamlit
   ↓ REST
RAG Application API
```

而不是直接 import 內部 QA service。

這樣未來學生 UI 可以直接取代 Streamlit，而 RAG backend 不需重做。

---

# 17. 建議的 Python v2 專案結構

這是 Platform v2 的目標方向。Codex 可以一次建立完整必要結構，但不要建立沒有責任、沒有實作、沒有測試計畫的空殼檔案。

```text
legal-qa/
│
├─ src/
│  └─ legal_qa/
│     │
│     ├─ api/
│     │  ├─ routes/
│     │  │  ├─ chat.py
│     │  │  ├─ retrieval.py
│     │  │  ├─ feedback.py
│     │  │  └─ health.py
│     │  └─ dependencies.py
│     │
│     ├─ domain/
│     │  ├─ legal.py
│     │  ├─ qa.py
│     │  ├─ retrieval.py
│     │  └─ conversation.py
│     │
│     ├─ services/
│     │  ├─ qa_service.py
│     │  ├─ retrieval_service.py
│     │  ├─ context_service.py
│     │  ├─ conversation_service.py
│     │  ├─ validation_service.py
│     │  └─ ingestion_service.py
│     │
│     ├─ adapters/
│     │  ├─ models/
│     │  │  └─ litellm.py
│     │  ├─ embedding/
│     │  │  └─ litellm.py
│     │  ├─ vector/
│     │  │  └─ qdrant.py
│     │  ├─ database/
│     │  │  └─ postgres.py
│     │  └─ observability/
│     │     └─ langfuse.py
│     │
│     ├─ prompts/
│     ├─ config/
│     └─ main.py
│
├─ scripts/
│  ├─ sync_laws.py
│  ├─ rebuild_embeddings.py
│  └─ evaluate.py
│
├─ data/
│  ├─ legal_provisions.json
│  └─ qa_test_questions.json
│
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  └─ evaluation/
│
├─ Dockerfile
├─ compose.yaml
├─ pyproject.toml
├─ .env.example
└─ README.md
```

Codex 可以建立完整專案結構，但每個新增 module 應有明確責任；避免只為了看起來完整而產生大量永遠不會使用的 placeholder。

---

# 18. Configuration、Secrets 與知識隔離邊界

## 18.1 核心原則

Platform v2 採用「開發知識隔離」原則。

Codex / 開發 AI 的責任是：

* 知道 Application 需要哪些 environment variables。
* 從 environment variables 讀取設定。
* 驗證必要參數是否存在。
* 建立安全的 unit / integration / smoke tests。
* 建立 Docker、Kubernetes 等部署所需的 configuration placeholder。
* 在參數已由 Human Operator 注入的前提下執行 Application 與測試。

Codex / 開發 AI **不需要知道，也不得主動探查**：

* Secret 實際值。
* Secret 儲存位置。
* Secret 使用哪一種檔案保存。
* Secret 如何由 Human Operator 載入。
* Human Operator 使用哪些 PowerShell script。
* Host machine 的 Secret 管理方式。
* Production Secret 的建立方式。
* Kubernetes Secret 的實際內容。
* Platform administrator credential。
* Secret rotation / backup 的實際操作方式。

這些資訊屬於 Human Operator / Platform Administrator 的責任範圍，不屬於 Application 開發知識。

開發端只需要假設：

```text
Application 啟動以前
Human Operator / Runtime
已經把必要 environment variables 準備完成。
```

---

## 18.2 Codex 可知的 Environment Variable Contract

目前 Platform v2 允許 Application 使用以下既有平台參數名稱：

```dotenv
POSTGRES_EXTERNAL_HOST=''
POSTGRES_INTERNAL_HOST=''
POSTGRES_PORT=''

POSTGRES_LITELLM_USER=''
POSTGRES_LITELLM_PASSWORD=''
POSTGRES_LITELLM_DATABASE=''

QDRANT_PUBLIC_URL=''
QDRANT_INTERNAL_HTTP_URL=''
QDRANT_INTERNAL_GRPC_ENDPOINT=''
QDRANT_API_KEY=''

LITELLM_PUBLIC_URL=''
LITELLM_INTERNAL_URL=''
LITELLM_API_KEY=''
```

Codex 可以在以下位置引用這些名稱：

```text
Pydantic Settings
Application configuration
Tests
Docker Compose
Kubernetes manifests
.env.example
README / deployment documentation
```

但只能使用：

```text
<REQUIRED>
<OPTIONAL>
空值
明顯的 fake / test value
```

不得出現任何實際 credential。

Codex 不得自行要求以下平台管理級資訊：

```text
POSTGRES_ADMIN_USER
POSTGRES_ADMIN_PASSWORD
POSTGRES_ADMIN_URL_*

LITELLM_MASTER_KEY
LITELLM_SALT_KEY
LITELLM_UI_PASSWORD
LITELLM_DATABASE_URL

REDIS_PASSWORD

其他 administrator
superuser
master key
platform internal secret
```

如果 Application 無法在目前權限下完成某項平台操作，Codex 應產生：

```text
需要的 SQL
需要的平台操作說明
診斷結果
需要 Human Operator 完成的前置條件
```

而不是要求 administrator credential。

---

## 18.3 PostgreSQL 開發階段限制

目前開發階段允許使用既有：

```text
POSTGRES_LITELLM_USER
POSTGRES_LITELLM_PASSWORD
POSTGRES_LITELLM_DATABASE
```

Codex 必須把它視為：

```text
Development-time existing credential
```

而不是：

```text
Production Legal QA identity
```

Codex 不得假設此帳號具有：

```text
superuser
database administrator
cluster administrator
```

權限。

Codex 不得：

```text
修改 LiteLLM 既有 application table
刪除 LiteLLM 既有資料
修改 LiteLLM schema
執行與 Legal QA 無關的 migration
建立破壞性 database migration
把目前帳號永久寫死為 production identity
```

如果需要 Legal QA 自己的資料表或 schema，應優先：

```text
建立隔離的 Legal QA schema / namespace
```

如果目前帳號權限不足，應停止該項平台修改並輸出安全診斷，例如：

```text
[BLOCKED] Required database permission is unavailable.
Required action: create schema legal_qa.
Human operator action required.
```

不得要求 PostgreSQL administrator password。

---

## 18.4 Runtime Configuration Boundary

Application 必須完全透過 environment variables 取得 runtime configuration。

Application 不得知道：

```text
environment variables 從哪個檔案來
Human Operator 如何載入
使用哪個 PowerShell script
Secret 存在哪個磁碟
Secret manager 使用哪個產品
Kubernetes Secret 如何被建立
```

Application 只應看到：

```text
Process Environment
        │
        ▼
Application Settings
```

例如 Python 可以：

```python
settings.qdrant_api_key
settings.litellm_api_key
settings.postgres_litellm_password
```

但 Application 不得自行尋找：

```text
.env
dev.env
secret.env
credentials.json
本機特定 secure directory
```

也不得自行讀取 repository 外的任何 credential file。

---

## 18.5 Development 與 Server Endpoint

同一份 Application code 必須支援 Development 與 Server / Kubernetes。

Development environment 主要可能提供：

```text
POSTGRES_EXTERNAL_HOST
POSTGRES_PORT

QDRANT_PUBLIC_URL

LITELLM_PUBLIC_URL
```

Server / Kubernetes environment 主要可能提供：

```text
POSTGRES_INTERNAL_HOST
POSTGRES_PORT

QDRANT_INTERNAL_HTTP_URL

LITELLM_INTERNAL_URL
```

以及相同類型的 runtime credential。

Application configuration layer 可以根據 runtime environment 選擇適當 endpoint。

但是：

```text
QAService
RetrievalService
EmbeddingService
ContextBuilder
HybridRanker
CitationValidator
其他 domain / service layer
```

不得知道：

```text
現在是在 Windows
現在是在 Kubernetes
現在使用 public endpoint
現在使用 internal endpoint
```

目標必須維持：

```text
同一份 source code
同一份 Application architecture

Development
→ External / Public endpoint

Server
→ Internal endpoint
```

環境切換只能影響 configuration，不得修改 RAG domain logic。

`QDRANT_INTERNAL_GRPC_ENDPOINT` 可以保留，但 Platform Baseline 如果 HTTP 已足夠，不需要強迫採用 gRPC。

---

## 18.6 Environment Variable Validation

Application 啟動時應驗證必要 configuration。

例如：

```text
POSTGRES_EXTERNAL_HOST / POSTGRES_INTERNAL_HOST
POSTGRES_PORT
POSTGRES_LITELLM_USER
POSTGRES_LITELLM_PASSWORD
POSTGRES_LITELLM_DATABASE

QDRANT_PUBLIC_URL / QDRANT_INTERNAL_HTTP_URL
QDRANT_API_KEY

LITELLM_PUBLIC_URL / LITELLM_INTERNAL_URL
LITELLM_API_KEY
```

缺少必要設定時，應回報：

```text
Missing required environment variable: LITELLM_API_KEY
```

不得：

```text
要求使用者貼出 LITELLM_API_KEY
搜尋本機取得 LITELLM_API_KEY
列出其他 environment variables
嘗試從其他檔案尋找 credential
```

Configuration 缺失是 runtime environment 尚未準備完成，不是 Application 應自行解決的問題。

---

## 18.7 Secret-safe Settings

敏感欄位必須使用安全型別。

例如 Pydantic：

```python
from pydantic import SecretStr

qdrant_api_key: SecretStr
litellm_api_key: SecretStr
postgres_litellm_password: SecretStr
```

需要呼叫外部服務時才取得實際值。

不得直接：

```python
print(settings.qdrant_api_key.get_secret_value())
```

也不得：

```python
logger.info(settings.model_dump())
```

除非已明確確認敏感欄位會被 redacted。

---

## 18.8 Smoke / Integration Test 責任

Codex 必須建立可以驗證實際平台連線的 smoke / integration test。

Codex 可以假設：

```text
Human Operator 在執行測試以前
已經完成所有必要 environment variable injection。
```

Codex 不需要知道 injection 的實作方法。

建議至少提供：

```text
scripts/smoke_test.py

或：

scripts/smoke_test_postgres.py
scripts/smoke_test_qdrant.py
scripts/smoke_test_embedding.py
scripts/smoke_test_chat.py
```

執行方式應保持簡單，例如：

```powershell
python scripts/smoke_test.py
```

測試只負責讀取目前 process environment。

不得接受：

```text
--api-key
--password
--master-key
--secret-file
```

等會讓 credential 出現在 command line history 的參數設計。

---

## 18.9 Smoke Test 安全輸出

測試成功時可以輸出：

```text
[PASS] PostgreSQL connected
[PASS] Qdrant connected
[PASS] LiteLLM connected
[PASS] bge-m3 embedding dimension = 1024
[PASS] campus-qa response
```

失敗時可以輸出：

```text
[FAIL] PostgreSQL authentication failed
[FAIL] Qdrant HTTP 401
[FAIL] Qdrant timeout
[FAIL] LiteLLM HTTP 500
[FAIL] LiteLLM timeout
[FAIL] Embedding dimension mismatch
```

可以輸出：

```text
HTTP status
exception type
timeout duration
model name
embedding dimension
service name
latency
```

不得輸出：

```text
Authorization header
API key
password
token
salt
Cookie
private key
credential-bearing DSN
完整 environment dump
```

如果測試失敗，Codex 應依據 redacted diagnostic output 進行分析。

不得因為測試失敗而要求 Human Operator 提供 credential。

---

## 18.10 Codex 的 Integration Test 行為

如果必要 environment variable 已存在於 Codex 當前執行環境，Codex 可以執行 smoke / integration test。

Codex只能使用：

```text
變數已存在
```

這個事實。

不得：

```text
輸出變數內容
追查變數來源
尋找 Secret file
詢問 Secret file 路徑
讀取 Human Operator 的 import script
查詢 OS credential store
檢查其他 shell profile
```

如果必要 environment variable 不存在，Codex 應回報：

```text
Integration test not executed:
required runtime environment variable is unavailable.
```

並提供：

```text
python scripts/smoke_test.py
```

等測試指令給 Human Operator。

不需要知道 Human Operator 如何準備該環境。

---

## 18.11 Docker Boundary

Codex 可以建立：

```text
Dockerfile
compose.yaml
.env.example
Docker README
```

但 Docker configuration 必須保持 environment-driven。

例如：

```yaml
environment:
  QDRANT_API_KEY: ${QDRANT_API_KEY}
  LITELLM_API_KEY: ${LITELLM_API_KEY}
```

不得：

```dockerfile
COPY .env .
COPY dev.env .
ARG REAL_PASSWORD
ENV API_KEY=<real-value>
```

Application Docker image 不得包含：

```text
real Secret
credential file
平台管理 credential
Human Operator Secret 管理工具
```

Docker image 只需要知道：

```text
需要哪些 environment variables。
```

Docker runtime 的實際參數注入方式屬於 Human Operator / Deployment responsibility。

### Docker 文件限制

Codex 在 Docker 文件中只需要提供：

```text
需要設定哪些 environment variables
如何 build image
如何啟動 container
哪些設定是 required / optional
```

不要描述 Human Operator 真實 Secret 的保存位置。

如果部署所需實際參數、Secret reference、namespace 或環境值尚未確定：

```text
使用 placeholder
```

例如：

```text
<POSTGRES_HOST>
<QDRANT_URL>
<LITELLM_URL>
<SECRET_REFERENCE>
```

實際部署值由 Human Operator 在部署階段自行替換。

---

## 18.12 Kubernetes Boundary

Codex 可以建立 Kubernetes deployment template。

例如：

```text
Deployment
Service
ConfigMap example
Secret reference example
Ingress example
HPA example
```

但這些檔案只能表達：

```text
Application 需要哪些設定。
```

例如：

```yaml
env:
  - name: QDRANT_API_KEY
    valueFrom:
      secretKeyRef:
        name: <SECRET_NAME>
        key: <QDRANT_API_KEY_KEY>
```

Codex 不需要知道：

```text
真正 Secret name
Secret value
Secret 怎麼建立
Secret 存放在哪
Cluster credential
kubeconfig
```

Deployment template 中可使用 placeholder，由 Human Operator 在正式部署階段自行替換。

Codex 不得：

```text
讀 Kubernetes Secret
decode Kubernetes Secret
尋找 kubeconfig credential
取得 cluster-admin credential
```

正式 Kubernetes Secret provisioning 不屬於 Codex 開發範圍。

---

## 18.13 Logging 與 Error Redaction

所有 log、exception、trace、test result 都必須經過 Secret-safe 設計。

禁止：

```python
print(os.environ)
logger.debug(os.environ)
logger.info(request.headers)
logger.info(settings)
```

如果 error object 可能含有：

```text
Authorization
credential-bearing URL
DSN
API key
Cookie
```

必須先 redact。

例如：

```text
postgresql://user:***@host/database

Authorization: Bearer ***

QDRANT_API_KEY=***
```

不得留下原始值。

---

## 18.14 Langfuse Boundary

Langfuse 可以記錄：

```text
model
embedding model
prompt version
question
provision_id
retrieval score
candidate count
Top K
latency
validation result
error category
```

但不得記錄：

```text
API key
password
Authorization header
Cookie
database credential
private key
platform Secret
```

未來正式學生版：

```text
student id
name
email
conversation content
retention policy
```

等個資政策尚未定案。

Codex 只能提供：

```text
redaction interface
metadata filtering
logging allowlist
```

不得自行決定正式 production 個資保存政策。

---

## 18.15 `.env.example`

Repository 可以包含 `.env.example`。

目的只有：

```text
描述 Application configuration contract。
```

例如：

```dotenv
POSTGRES_EXTERNAL_HOST=<OPTIONAL>
POSTGRES_INTERNAL_HOST=<OPTIONAL>
POSTGRES_PORT=<REQUIRED>

POSTGRES_LITELLM_USER=<REQUIRED>
POSTGRES_LITELLM_PASSWORD=<REQUIRED>
POSTGRES_LITELLM_DATABASE=<REQUIRED>

QDRANT_PUBLIC_URL=<OPTIONAL>
QDRANT_INTERNAL_HTTP_URL=<OPTIONAL>
QDRANT_INTERNAL_GRPC_ENDPOINT=<OPTIONAL>
QDRANT_API_KEY=<REQUIRED>

LITELLM_PUBLIC_URL=<OPTIONAL>
LITELLM_INTERNAL_URL=<OPTIONAL>
LITELLM_API_KEY=<REQUIRED>
```

`.env.example` 不代表 Codex 應建立真正 `.env`。

Codex 不得：

```text
自動建立含真值的 .env
搜尋其他 .env
複製外部 credential
要求 Human Operator 把實際值填入 repository
```

---

## 18.16 `.gitignore`

Repository 至少應避免常見 Secret file 被加入 Git：

```gitignore
.env
.env.*
!.env.example

secrets/
*.key
*.pem
*.p12
```

`.gitignore` 是 source-control safety mechanism。

Codex 不需要知道 Human Operator 實際使用哪一種 Secret storage。

---

## 18.17 `AGENTS.md` Security Rules

Repository 根目錄的 `AGENTS.md` 至少應包含以下等價規則：

```text
SECURITY / SECRETS RULES

- Treat runtime credentials as externally injected configuration.
- Only rely on documented environment-variable names.
- Never request, discover, read, display, print, log, commit, or persist real credentials.
- Do not search for .env files, credential files, secret directories, shell profiles, credential stores, or secret-loading scripts.
- Do not attempt to determine where or how the human operator stores or loads secrets.
- Never print all environment variables or unredacted settings.
- Never log Authorization headers, API keys, passwords, salts, cookies, private keys, or credential-bearing connection strings.
- Do not request administrator, superuser, master-key, kubeconfig, or cluster-admin credentials.
- Do not reveal or decode Kubernetes Secret values.
- If required runtime environment variables are already available, tests may use them without displaying their values.
- If required runtime environment variables are unavailable, provide the human operator with a safe test command instead of requesting credentials.
- Docker and Kubernetes files must contain environment-variable references or placeholders only.
- Real deployment values and Secret provisioning are the responsibility of the human operator / deployment environment.
```

---

## 18.18 完成判定

Configuration / Secret architecture 完成時必須能證明：

```text
1. Application 只依賴 environment-variable contract。

2. Application 不知道 Secret 的實際儲存位置。

3. Application 不知道 Human Operator 如何載入 Secret。

4. Codex 不需要任何 administrator / master credential。

5. 缺少 runtime parameter 時能安全 fail-fast。

6. Human Operator 準備好 runtime environment 後，
   Application 可以直接啟動。

7. Smoke test 可以直接使用目前 process environment。

8. Smoke test 不會輸出 credential。

9. Development 與 Server 可以使用不同 endpoint，
   但共用相同 RAG domain code。

10. Docker image 不包含 Secret。

11. Docker / Kubernetes template 只包含 variable reference
    或 placeholder。

12. 真實 Docker / Kubernetes deployment value
    可以由 Human Operator 後續自行替換或注入。

13. Log、exception、test output、Langfuse trace
    不會洩漏 credential。

14. 即使 Codex 完全不知道 Secret 怎麼保存，
    仍然可以完成 Application 開發、unit test、
    configuration validation 與可執行的 integration test tooling。
```

## 18.19 最終責任邊界

整體責任應固定為：

```text
Human Operator / Runtime
        │
        │ 準備 runtime environment
        ▼
Environment Variables
        │
        ▼
Application Settings
        │
        ▼
Legal QA Platform v2
        │
   ┌────┼────┐
   ▼    ▼    ▼
Postgres Qdrant LiteLLM
```

Codex 的知識從：

```text
Environment Variables
```

開始。

Codex 不需要，也不應知道 Environment Variables 上游的 Secret 管理方式。

這個邊界是 Platform v2 的正式 Security / Knowledge Isolation Boundary。
---

# 19. Load Test 是正式 requirement

Platform MVP 上 server 後必須能測：

```text
1 concurrent
5 concurrent
10 concurrent
20 concurrent
50 concurrent
100 concurrent
```

實際最大值可依平台資源逐步增加。

至少紀錄：

```text
RPS
p50 latency
p95 latency
p99 latency
error rate
embedding latency
Qdrant latency
keyword latency
LLM latency
total latency
```

要區分：

```text
App 本身的 concurrency 能力
```

與：

```text
LiteLLM / model backend 的 parallel / RPM / TPM 限制
```

目前現有 key 已知為 5 parallel，因此不能用 model quota 當成 App server 的最大能力判定。

---

# 20. Codex 全面實作順序

以下 Phase 不再代表「每一步都要停下等開發者」，而是 Codex 建置整體時的依賴順序與驗收切點。

Codex 應能自主一路完成 Platform Baseline；每個 Phase 都要留下可獨立驗證的 test / script / trace，方便完成後逐層理解。

## Phase 0 — 新版骨架與 Data Contract

1. 建立 v2 project skeleton。
2. 搬入 `legal_provisions.json`。
3. 搬入 `qa_test_questions.json`。
4. 沿用 / 整理上一版 Pydantic schema。
5. 建 loader / validation。
6. 建立基本 config / dependency boundary。
7. 建立 `.env.example`，內容只包含第 18.2 節允許的環境變數名稱與 placeholder。
8. 建立 / 更新 `AGENTS.md` 的 Security / Secrets Rules。
9. 建立資料 contract tests。

## Phase 1 — Platform Client / Adapter Layer

建立清楚 interface / adapter：

```text
EmbeddingProvider
ChatModel / ModelGateway
VectorStore
LegalRepository
Observability
```

第一版 implementation：

```text
EmbeddingProvider → LiteLLM / bge-m3
ChatModel         → LiteLLM / campus-qa
VectorStore       → Qdrant
LegalRepository   → PostgreSQL
Observability     → Langfuse
```

避免 QAService 直接散落 HTTP、SQL 或 Qdrant client 細節。

所有 adapter 的 credential 必須只從 Settings / runtime environment 取得；不得從 source file、hard-coded constant 或 repository 內的真實 `.env` 取得。

## Phase 2 — Embedding / Qdrant 基礎

1. 呼叫 bge-m3。
2. 驗證 1024 dimensions。
3. 建立版本化 collection。
4. Point / payload mapping。
5. upsert / retrieve / vector search。
6. integration tests。

## Phase 3 — 法規完整同步

完成：

```text
JSON validation
→ PostgreSQL master data upsert
→ content / embedding hash compare
→ incremental bge-m3 embedding
→ Qdrant upsert
→ full snapshot / partial sync semantics
```

要能安全重跑並避免 unchanged provision 重算向量。

## Phase 4 — Retrieval Baseline

完成並分開測試：

```text
Qdrant Vector Retrieval
PostgreSQL Keyword Retrieval
Hybrid Ranking
Top K / min score
```

第一版盡量沿用上一版 Hybrid 行為，不加入 reranker。

## Phase 5 — Context / Prompt / Generation

完成：

```text
Context Builder
長條文相關段落選取
Prompt 建立
LiteLLM / campus-qa
max_tokens 必填處理
Structured Output
```

## Phase 6 — Validation / Citation

沿用上一版核心規則：

```text
Pydantic validation
Citation allowlist
Provision ID validation
response cleanup
```

LLM response 不可未驗證直接成為 final application response。

## Phase 7 — 完整 QA Application Core

組合：

```text
Normalize
→ Embedding
→ Vector Retrieval
→ Keyword Retrieval
→ Hybrid Ranking
→ Context Builder
→ Prompt
→ Model
→ Structured Validation
→ Citation Validation
→ Answer
```

建立可直接從 CLI / test 呼叫的 QA Core，不能只能從 UI 使用。

## Phase 8 — Langfuse Observability

加入完整 trace / span：

```text
normalize
embedding
vector_retrieval
keyword_retrieval
hybrid_ranking
context_build
generation
response_validation
citation_validation
```

Langfuse failure 原則上不得讓 QA Core 無法回答。

## Phase 9 — RAG Profile / Experimentability

將可調參數 profile 化：

```text
chat model
embedding model
candidate_k
top_k
min_score
vector_weight
keyword_weight
prompt version
reranker_enabled (第一版 false)
```

正式演算法只能有一份 implementation；UI / n8n / CLI 不可各自複製 Hybrid 邏輯。

## Phase 10 — REST Application API

建立正式 REST boundary。

若 repository 沒有既定 application framework，可選擇與 Python RAG Core 最直接、容易替換的實作，並用 ADR 記錄。REST contract 不得綁死 framework-specific model。

至少提供：

```text
POST /api/v1/chat
POST /api/v1/retrieve
POST /api/v1/feedback
GET  /health
GET  /ready
```

實驗 endpoint 是否公開給 production client 應與正式 chat endpoint 分離。

## Phase 11 — Conversation 基礎能力

建立 application-controlled conversation schema / repository。

第一版可以使用簡單策略：

```text
最近 N 則 conversation messages
+
本次 RAG context
```

但要區分 Conversation Context 與 RAG Context。

永久聊天資料不可只存在 LangChain / LangGraph / n8n memory。

## Phase 12 — Streamlit Platform MVP

Streamlit 改為：

```text
Streamlit
→ REST API
→ QA Core
```

保留 100 題測試操作與必要人工檢視能力。

## Phase 13 — Evaluation

完整跑既有 100 題。

至少輸出：

```text
retrieval recall / hit
expected provision hit
citation result
answer result / validation result
latency
error
profile / prompt / model metadata
```

建立 `platform-baseline-v1` 可重現結果。

## Phase 14 — Docker

建立 production-oriented Application image。

外部服務不打包進 App image：

```text
PostgreSQL
Qdrant
LiteLLM
Langfuse
Models
```

本機可提供必要 Compose / dev configuration 方便測試。

## Phase 15 — Kubernetes Deployment

建立可審查的 manifests / Helm/Kustomize 方案（依 repository 現況選擇，不必過度工程化）：

```text
Deployment
Service
ConfigMap
Secret references
health/readiness probe
Ingress（若正式 host 尚未決定可保留範本）
resources requests/limits
replica strategy
```

不要把真實 secret commit 進 repository。

## Phase 16 — Load Test

建立 load test script / scenario，能逐步測：

```text
1
5
10
20
50
100 concurrent
```

並區分：

```text
Application API latency
Embedding latency
Qdrant latency
PostgreSQL latency
LLM latency
LiteLLM quota / model parallel bottleneck
```

## Phase 17 — n8n AI Lab（可在 Baseline 完成後建立）

n8n 可以用來：

```text
100 題 batch
Profile A/B
Prompt / model experiments
model smoke test
ingestion orchestration
```

n8n 應呼叫正式 RAG Application API / reusable service，不重新實作第二套 production Hybrid / Validation logic。

## Phase 18 — Advanced RAG Experiments（Baseline 後）

Baseline 完成後才開始比較：

```text
bge-reranker-v2-m3 on/off
Top K
candidate K
Hybrid weights
Prompt versions
Model variants
Qdrant hybrid search
Query rewrite
```

LangGraph / Agent 仍只有在流程出現實際 branch / loop / retry / tool orchestration requirement 時才評估。

# 21. 第一版明確「不要做」

在 Platform Baseline 完成前不要自行加入：

```text
bge-reranker-v2-m3
LangGraph
Agent
Redis memory
Long-term memory
Semantic user memory
自動抓法規
自動更新法規
多 Knowledge Base Router
複雜 query rewrite
n8n production RAG engine
大量 LangChain abstraction
```

如果 Codex 認為某項現在就必須加入，必須先說明「不加會阻塞哪個當前 requirement」，不要直接加入。

---

# 22. Platform MVP v1 Acceptance Criteria

第一階段成功不是看 UI 漂不漂亮，而是以下條件成立。

## Data

- 原有法規 JSON 可通過 schema。
- Provision stable ID 保留。
- 題庫仍可讀。

## Embedding

- bge-m3 API 可正常呼叫。
- 1024 dimensions 驗證成功。
- 全部正式條文完成新 embedding。

## Vector

- Qdrant collection 建立。
- 法條可 upsert / search。
- payload 能追到 PostgreSQL provision。

## Retrieval

- Vector retrieval 成功。
- Keyword retrieval 成功。
- Hybrid ranking 成功。
- Top K 可設定。

## Generation

- campus-qa REST API 成功。
- max_tokens 正確提供。
- Prompt 正常。

## Validation

- Structured output validation 成功。
- Citation allowlist 保留。

## Observability

- Langfuse 可看到一題完整 trace。
- 至少可拆 embedding / retrieval / generation / validation latency。

## Evaluation

- 100 題能重新執行。
- 能量測 retrieval recall / citation / answer result。
- 可以保存 Platform Baseline。

## Deployment

- Application 有 Docker image。
- 可部署 server / Kubernetes。
- health / readiness 可檢查。

## Load

- 可執行 concurrency test。
- 可區分 App 與 Model Gateway / Model backend 的瓶頸。

---

# 23. 尚未完全決定的事項與 Codex 自主決策邊界

下列事項長期仍未正式定案：

1. 學生 Application REST API 最終 framework。
2. Student authentication / SSO。
3. Conversation retention policy。
4. 個資 / log retention policy。
5. Langfuse 正式 server topology / sizing。
6. Qdrant collection 最終 naming convention。
7. 外部模型 provider。
8. 正式 model routing policy。
9. 正式 rate limit / quota。
10. Redis 正式加入時機。
11. n8n 是否會進任何 production request path。
12. LangChain 是否值得導入，以及導入範圍。
13. LangGraph 導入時機。

### Codex 可以自行決定的部分

為了讓 Platform v2 可以完整 build，對於不具破壞性的 MVP implementation choice，Codex可以自行選擇合理方案，例如：

```text
Python package layout
測試框架與測試資料夾組織
HTTP client library
Qdrant Python client 使用方式
PostgreSQL async/sync client 選擇
Application REST API 的 MVP implementation framework
Docker base image
Kubernetes manifests 的基本組織
local dev compose 的結構
```

但必須：

```text
用 ADR 說明理由
保持 adapter / contract 可替換
不要讓 framework-specific type 洩漏到 domain core
不要把暫時選擇描述成永遠不可更換
```

### Codex 不應自行定案的部分

以下若缺乏明確資訊，不要硬做 production policy：

```text
正式學生 SSO / authorization
正式個資保存期限
正式 production domain / ingress routing
正式外部模型 credential
正式學生 quota
正式資料刪除政策
正式安全 / audit policy
```

可先建立 interface、config placeholder、schema 或文件，但不要虛構正式值。

# 24. Codex 問題處理方式

若遇到錯誤，請先定位是哪一層：

```text
Data / Schema
Embedding
Qdrant
PostgreSQL Keyword
Hybrid Ranking
Context Builder
Prompt
Chat Model
Structured Output
Citation Validation
REST API
Docker
Kubernetes
Load / Concurrency
Observability
```

不要直接以「重寫整條 pipeline」作為第一反應。

每次 debugging 優先回答：

```text
Expected input 是什麼？
Actual input 是什麼？
Expected output 是什麼？
Actual output 是什麼？
錯誤第一次出現在哪一層？
```

---

# 25. 建議直接交給 Codex 的啟動 Prompt

可把以下內容直接交給 Codex：

```text
請先完整閱讀專案根目錄的 legal_qa_platform_v2_codex_full_build_brief.md，並把它視為本次 Platform v2 重構的主要架構與需求文件。

本次改採「Codex 全面實作模式」。

你可以自主建立並完成整套 Platform v2，不需要逐 Phase 停下等待我手動輸入程式碼。請直接進行必要的 repository 盤查、架構設計、實作、測試、整合與文件建立，直到 Platform Baseline 能完整執行。

核心要求：

1. 保留上一版已驗證的 Pydantic / JSON schema、legal_provisions.json、qa_test_questions.json，以及主要 RAG 行為與 validation 規則。
2. 舊的 Ollama / embeddinggemma / pgvector runtime implementation 不作為 v2 架構包袱。
3. Platform v2 使用現有平台資源：Qdrant、PostgreSQL、LiteLLM、campus-qa、bge-m3；第一個 baseline 先不用 bge-reranker-v2-m3。
4. 所有條文使用 bge-m3 重新產生 1024 維 embedding 並存入 Qdrant。
5. 第一版仍保留 Vector Retrieval + PostgreSQL Keyword Retrieval + Hybrid Ranking + Top K + Context Builder + Structured Output + Citation Validation 的主要流程。
6. Langfuse 從 v2 導入，記錄主要 RAG spans，但 Langfuse failure 不應讓 QA Core 無法服務。
7. RAG domain logic 必須存在於可測試、可替換的 Application Core，不要把唯一 production logic 放進 n8n、LangChain chain 或單一巨大 workflow。
8. 建立 REST Application API；實際 Python web framework 若 repository 沒有既定選擇，可以自行採合理 MVP implementation，但要用 ADR 記錄，且 REST contract 與 domain core 不得被 framework 綁死。
9. Streamlit 改為 REST client，不直接 import QAService。
10. 建立基本 conversation persistence / context 能力，永久對話資料由 Application DB 掌握。
11. 完成 Docker image、server/Kubernetes deployment 範本、health/readiness、100 題 evaluation 與 load test。
12. 不要 commit 真實 secrets。Codex 不得要求、讀取、顯示、log 或保存真正 password / API key / salt / token。
13. 只允許使用 brief 第 18.2 節列出的開發環境變數契約；真實值位於 Codex workspace 外，由 human operator 在 runtime 注入。
14. 本機開發使用 external/public endpoints；Kubernetes 使用 internal endpoints。必須是同一份 source code / Docker image，只更換 runtime configuration。
15. 需要真正 PostgreSQL / Qdrant / LiteLLM credential 的 integration test 必須由 Codex 產生安全 test script，再由 human operator 執行；不得要求我貼出 Secret。
16. Kubernetes manifests 只能使用 ConfigMap / secretKeyRef 等 reference，不得包含真值，也不得讀取或 decode cluster Secret。
17. Baseline 完成前不要擅自加入 reranker、Agent、LangGraph、長期 semantic memory、自動抓法規等進階功能。

最重要的交付要求：

這次不是只要求「可以跑」。我要在完成後逐層理解並接手維護，所以請同時建立完整的理解文件，至少涵蓋：

- architecture
- end-to-end data flow
- ingestion / embedding
- retrieval / hybrid ranking
- context / prompt
- model gateway
- validation / citation
- conversation
- Langfuse observability
- REST API
- database
- tests / evaluation
- Docker / Kubernetes deployment
- load testing
- troubleshooting
- architecture decision records (ADR)

每個重要模組都要能說清楚 input、output、dependency、configuration、failure mode 與如何測試。

工作方式：

A. 先盤查現有 repository 與上一版可保留資產。
B. 建立簡短 implementation plan，但不要停下等我確認；沒有破壞性風險就直接執行。
C. 按 brief 的依賴順序完成整套 Platform Baseline。
D. 每完成重要層就執行對應 test / smoke test，不要最後才一次測。
E. 遇到缺少正式 secret、production domain、SSO/個資政策等不可自行猜測的資訊時，使用清楚 placeholder / interface 並記入文件；不要阻塞其他可完成工作。
F. 最後輸出完整 completion report：做了什麼、檔案結構、如何啟動、如何同步法規、如何跑 100 題、如何看 Langfuse、如何 Docker build、如何部署、如何 load test、如何由 human operator 載入外部 dev.env 執行真實 smoke test、Kubernetes 如何以 ConfigMap / Secret 注入設定、哪些項目仍需人工提供 production 設定。

如果現有 repository 的實際狀況與 brief 有衝突，以「不破壞既有法規資料與已驗證 schema / domain semantics」為最高優先，並把差異記錄在 ADR 或 migration notes。

現在請開始盤查並直接建立 Platform v2。
```

# 26. Build 完成後的 Understand Phase 教學順序

Codex 完成後，不要用「逐檔案從第一行開始念」的方式理解專案。

應照一筆真實 QA request 從外到內追蹤：

```text
Streamlit / Client
→ REST API
→ QAService
→ Conversation Context
→ EmbeddingProvider
→ LiteLLM / bge-m3
→ Qdrant Vector Retrieval
→ PostgreSQL Keyword Retrieval
→ HybridRanker
→ ContextBuilder
→ Prompt
→ LiteLLM / campus-qa
→ Structured Output
→ CitationValidator
→ Response
→ Langfuse Trace
```

每一層的學習都回答五個固定問題：

```text
1. 這一層為什麼存在？
2. Input / Output 長什麼樣？
3. 實際 code 在哪裡？
4. 哪些設定可以調？
5. 出錯時如何重現、觀察、測試與修正？
```

建議理解順序：

```text
A. 先跑一題並看完整輸出
B. 用 Langfuse 看同一題的完整 trace
C. 從 retrieval 開始追 provision_id / score
D. 追 ContextBuilder 如何組 context
E. 追 prompt 與 model request / response
F. 追 Pydantic / citation validation
G. 再看 ingestion 如何產生同一筆 Qdrant point
H. 最後才看 Docker / Kubernetes / concurrency
```

完成 Understand Phase 的判定不是「看完文件」，而是開發者能自行完成至少以下修改並知道如何驗證：

```text
改 Top K
改 Hybrid weight
新增 / 修改 Prompt version
切換 chat model profile
重跑一部法規的 embedding
查一筆 provision 在 PostgreSQL / Qdrant / Langfuse 的對應
定位一個 citation validation failure
定位一個 LiteLLM timeout
執行 100 題 evaluation
執行 load test 並判斷瓶頸位於 App 還是 Model backend
```

---

# 27. 最終架構心法


本專案長期應遵循：

> AI 核心 Python 化、系統服務 REST 化、Infrastructure 服務化、Domain Logic 自己掌握、Framework 可替換、Observability 從早期就建立。

更簡化地說：

```text
資料與規則       → 我們掌握
RAG Core         → 我們掌握
REST Contract    → 我們掌握

模型執行         → LiteLLM / Model Services
Vector Search    → Qdrant
Application Data → PostgreSQL
Observability    → Langfuse
AI Lab Workflow  → n8n
Framework        → 可替換工具
```

最重要的目標不是「少寫程式」，而是：

> Codex 先把整體架構完整、正確地建立起來；之後開發者能沿著資料流逐層理解每一個模組為什麼存在、資料怎麼流、哪裡可以調、壞掉時去哪裡查，最終能獨立維護與修改，而不是永遠依賴 Codex。

