# Troubleshooting

診斷順序由內到外：configuration → process/API → PostgreSQL → Qdrant → LiteLLM →
RAG pipeline → UI/deployment → observability。每一步只收集必要且已遮罩的證據；
不要 dump environment、settings、headers、DSN、external response body 或 Kubernetes
Secret。

## 安全的第一輪檢查

```powershell
python scripts/verify_repository.py
python -m pytest
python scripts/smoke_test.py
Invoke-WebRequest http://127.0.0.1:8000/health
Invoke-WebRequest http://127.0.0.1:8000/ready
```

若 runtime environment 尚未由 Human Operator 準備，`smoke_test.py` 應只報缺少的
名稱並停止 live checks。不要要求值、追查來源或嘗試讀取 credential 檔案。

安全證據包括：application version、service/stage、HTTP status、exception type、
error category、timeout/latency、embedding dimension、candidate count、stable
`provision_id`、validation result、trace/request ID（確認不含敏感資訊後）。

## Configuration

| 症狀 | 檢查 | 處理 |
| --- | --- | --- |
| 啟動列出 missing names | 對照 `docs/configuration.md` 的 13-name contract | 由 Human Operator 在 process 啟動前注入；不要貼值 |
| 選到錯誤 endpoint 類型 | 查看 `safe_status()` 的 internal/public/missing 類別 | internal 欄位有值時會優先；修正 runtime injection，不改 domain logic |
| Port validation error | 只確認型別與 1–65535 範圍 | 由 Human Operator 修正設定，不列印完整 settings |
| Langfuse 沒有 trace | 目前 contract 未包含 Langfuse configuration | 預期使用 no-op；QA 應繼續，勿新增未核准 env knob |

## Python process 與 API

API 的正式啟動入口：

```powershell
uvicorn legal_qa_platform.api.app:app --host 0.0.0.0 --port 8000
```

- Import error：確認從正式 repository 安裝 package，執行
  `python -m pip install -e ".[dev,ui,observability]"`；不可加入唯讀參考 path。
- `Required data file is missing`／`RAG profile is missing`：確認process從包含
  repository-owned `data/`與`profiles/`的runtime root啟動；Docker的root固定為
  `/app`。不要搜尋host其他目錄或改指向reference repository。
- `/health` 失敗：先處理 process crash、import/config composition 或 port binding。
- `/health` 成功、`/ready` 失敗：process 存活，但PostgreSQL schema/published
  snapshot、Qdrant service/collection或LiteLLM至少一項未ready；先看response中的
  boolean check名稱，再依下列三層safe smoke結果判讀。
- 4xx validation：只記錄 schema error path/category，不記錄整份 question 或 body。
- 5xx：使用 sanitized error category；不得直接輸出 exception object 或 external body。

## PostgreSQL

| Error 類別 | 意義與安全處理 |
| --- | --- |
| timeout / connection refused | 確認 endpoint 類型、port 與部署網路可達性；不要顯示 DSN |
| authentication failed | 只回報 authentication 類別；由 Human Operator 檢查注入，不要求 password |
| permission denied | Migration 只能要求 application-owned schema/table 權限；不得索取 admin credential |
| missing relation/schema | 以 `python scripts/migrate.py` 執行 repeatable migration，再重跑 smoke |
| `published_snapshot=false` | 先確認migration，再以正確full/partial mode完成同步；不要把running/failed run手動標成成功 |
| keyword latency 高 | 查看 index/query plan 的非敏感摘要、pool wait 與 candidate count，不記錄 raw question |

不得修改、drop 或 migrate 無關的 LiteLLM tables。現有資料庫身分不代表 production
identity，也不代表 administrator 權限。

## Qdrant

| Error 類別 | 意義與安全處理 |
| --- | --- |
| 401/403 | 回報 status 與 service；由 Human Operator 檢查 runtime injection，不顯示 key/header |
| timeout/unavailable | 檢查 public/internal endpoint 類型、network 與 Qdrant readiness |
| `qdrant_collection=false`／collection missing | 確認 migration/sync sequence、profile collection與1024維Cosine contract；不要臨時改用 pgvector |
| dimension mismatch | `bge-m3` 必須是 1024；停止寫入，檢查 model/collection contract |
| provision 缺漏或 stale | 比對 PostgreSQL current state、`provision_id`、hash/model identity 與最新 sync run |

Changed provision 的舊 vector 不可繼續服務。只有確認輸入是完整權威快照時才可重跑
`python scripts/sync_laws.py --mode full-snapshot`；一般修正或少量資料用
`--mode partial`，不可從 partial input 推論刪除。

## LiteLLM

| Error 類別 | 意義與安全處理 |
| --- | --- |
| 401/403 | 只記錄 status；由 Human Operator 檢查 injection，不顯示 Authorization header |
| 429 | 分類為 RPM/TPM/parallel quota，採受控退避；不把它誤判為 FastAPI 容量 |
| timeout | 分別記錄 embedding 或 generation stage latency，確認 gateway/model queue |
| embedding dimension mismatch | 期待 1024；停止同步或回答，避免污染 Qdrant projection |
| chat 500 | 確認 adapter request 有明確 `max_tokens`；不記錄 request/response body |
| invalid structured response | 進入 validation error，不讓未驗證 model output 成為 final answer |

## Retrieval、generation 與 citation

沒有答案或引用不正確時依序檢查：

1. 正規化後是否仍保留法規名、條號與關鍵片語；
2. Qdrant vector 與 PostgreSQL keyword 是否各自產生 candidate；
3. Hybrid score、minimum score、Top K 與 dedup 是否使用同一 profile；
4. Candidate 是否是 current provision，且 Qdrant hash/model identity 與 PostgreSQL
   相符；
5. 長條文 context extraction 是否保留相關段落與 citation identity；
6. `campus-qa` output 是否通過 structured schema；
7. citation 是否位於本次 context 的 allowlist。

Baseline 沒有 reranker；不要為修一題而在 UI、n8n 或 evaluator 另寫排序邏輯。
重現 regression 使用 `python scripts/evaluate.py`，比較相同 dataset/profile/prompt/model
metadata，且 expected values 不得進 production prompt。

## Streamlit

- UI 必須以 `--api-base-url` 啟動；它不讀新的 application environment knob。
- 本機 UI 指向 `http://127.0.0.1:8000`；Compose UI 由既有 command 指向 API service。
- UI health 成功但問答失敗時，先測 API `/health`、`/ready` 與 smoke，不在 UI
  process import QA core 或直接連 PostgreSQL/Qdrant/LiteLLM。
- 瀏覽器錯誤或 response 顯示前仍須經 API structured/citation validation。

## Docker

```powershell
docker compose up --build --detach
docker compose ps
```

- API/UI container unhealthy：先看 health status 與已遮罩的 application error category。
- API 無法連 external services：Compose 只打包 application；PostgreSQL、Qdrant、
  LiteLLM、Langfuse 不會自動啟動。
- UI 等待 API：`depends_on` 以 API health 為條件；確認 API `127.0.0.1:8000` 與 UI
  `127.0.0.1:8501` 的 loopback binding。
- 不使用可能展開 process environment 的 config/inspect dump 來求助。分享 logs 前先
  確認只有 allowlisted fields。

## Kubernetes

Manifests 是 placeholder template。Image、ConfigMap values、Secret reference、Ingress
host/class/TLS、namespace 與 cluster policy 必須由 Human Operator 決定。

- startup probe 失敗：先區分 process/configuration 與 image/import 問題。
- readiness 失敗：依回傳的`postgresql`、`published_snapshot`、`qdrant`、
  `qdrant_collection`、`litellm` boolean診斷；Langfuse不在其中。
- liveness 失敗：檢查 process deadlock/crash，不用 external dependency failure 觸發
  不必要 restart。
- read-only filesystem error：application 可寫入位置應限於掛載的 `/tmp`；持久狀態
  應在 PostgreSQL/Qdrant。
- HPA scale 但 latency 不降：檢查 LiteLLM/model quota 與外部 dependency，不只加 pod。

Codex 不讀 kubeconfig、不查詢/describe/decode Secret，也不要求 cluster-admin。
Cluster evidence 由 Human Operator 以其核准工具取得，只分享已遮罩的 status/event。

## 安全 escalation template

回報問題時提供：

```text
timestamp / application version:
environment class: local, container, or Kubernetes
endpoint class: internal, public, or missing
failing stage/service:
safe command executed:
HTTP status / exception type / error category:
latency and concurrency:
health / readiness result:
recent application change:
sanitized request or trace identifier:
```

不要附 environment dump、settings repr、headers、credential、DSN/完整 endpoint、
production question/conversation、Secret manifest、kubeconfig 或未遮罩的 logs。
