# Testing

測試分為離線測試、live integration、100 題 evaluation，以及 repository
independence／secret-safety gate。Live 測試只有在 Human Operator 已把
[允許的 runtime names](configuration.md) 注入目前 process 時才連外；任何測試都
不得顯示值或追查值的來源。

## 準備開發環境

需要 Python 3.11 以上。從 repository root 安裝開發與可選 UI／observability
dependencies：

```powershell
python -m pip install -e ".[dev,ui,observability]"
```

安裝 observability dependency 不會啟用 Langfuse；目前預設仍是 no-op、fail-open。

## 離線 test gate

完整 pytest suite：

```powershell
python -m pytest
```

需要明確排除 live marker 時：

```powershell
python -m pytest -m "not integration and not evaluation"
```

離線 suite 至少覆蓋：

- legal JSON/schema、stable `provision_id`、global `sort_order`、article/current-text
  規則與 full/partial snapshot 語意；
- content hash、embedding input hash、1024-dimensional vector validation 與
  unchanged-item reuse；
- question normalization、PostgreSQL keyword candidate、Qdrant vector candidate、
  deterministic hybrid ranking、configurable Top K 與 context extraction；
- prompt boundary、structured output、citation allowlist、response cleanup 與錯誤
  mapping；
- conversation context 與 RAG context 分離；
- endpoint precedence、missing-name diagnostics、`SecretStr` redaction；
- Langfuse no-op 與 span failure 不影響 QA result；
- FastAPI transport schema 與 application service 不洩漏 framework type。

靜態與 build checks：

```powershell
python -m ruff check .
python -m mypy
docker build --tag legal_qa_platform:local .
```

若只驗證 Python wheel，可在隔離的 build workspace 使用標準 wheel build；不得把
repository 外部 reference path 或 credential 檔案加入 build context。

## Data contract

Checked-in authoritative inputs 是 `data/legal_provisions.json` 與
`data/qa_test_questions.json`。測試需驗證資料可解析、ID 與排序規則一致、題庫恰有
100 題，並確認 evaluation-only 的 expected answer、keywords 與 provision IDs
不會進入 production prompt。

`schemas/`保存domain/API Pydantic contract的versioned JSON Schema。修改相關model後
執行`python scripts/export_schemas.py`，並由離線測試／repository verification確認
輸出deterministic且與runtime model一致；不要手工維護第二套schema定義。

法規同步先執行 non-destructive migration，再依輸入語意選擇模式：

```powershell
python scripts/migrate.py
python scripts/sync_laws.py --mode full-snapshot
python scripts/sync_laws.py --mode partial
```

只有完整且權威的資料集能用 `full-snapshot`；`partial` 不得把未出現的 provision
解讀為刪除。同步需要 live PostgreSQL、Qdrant 與 LiteLLM，所以不屬於離線 gate。

## Live integration / smoke

安全的統一入口：

```powershell
python scripts/smoke_test.py
```

Smoke test 只讀目前 process environment，不能接受 API key、password 或 Secret
file flags。它應分層確認：

1. PostgreSQL 可連線、application schema存在，且目前profile有成功published snapshot；
2. Qdrant readiness、collection contract 與 authenticated request；
3. LiteLLM readiness；
4. `bge-m3` embedding 回傳恰為 1024 dimensions；
5. `campus-qa` chat request 明確包含 `max_tokens` 並取得可驗證 response。

安全輸出只包含 `[PASS]`／`[FAIL]`、service、HTTP status、error category、latency、
model 與 dimension。不得包含 header、response body、DSN、URL credential、settings
或 environment dump。缺少設定時，回報 unavailable names 並停止 live 部分；不要
要求 Human Operator 提供值。

若 pytest 中另有 live marker，可由已準備好 runtime environment 的 Human Operator
執行：

```powershell
python -m pytest -m integration
```

## 100 題 evaluation

在法規完成同步、API dependencies ready 後執行：

```powershell
python scripts/evaluate.py
```

Evaluation 必須使用同一份 production retrieval、ranking、context、generation 與
validation implementation，不得在 evaluator 複製第二套 RAG。每題至少記錄：

- expected provision hit／retrieval recall；
- citation 與 structured-answer validation result；
- answer result、error category 與 stage/total latency；
- profile、prompt version、model 與 retrieval parameters。

報告不得把 expected values 送進 model prompt，也不得包含 credential 或未經核准的
conversation data。比較結果時固定 dataset、profile 與 prompt version；baseline
不啟用 reranker。

## Independence 與 secret-safety

```powershell
python scripts/verify_repository.py
```

Verification 至少證明：

- source、tests、scripts、Docker build 與 runtime 沒有 import、symlink、absolute
  path、copy 或 network dependency 指向唯讀參考 repository；
- 所有保留的 JSON、schema、fixtures 與 domain behavior 均存在正式 repository；
- tracked artifacts 不含真實 credential、credential loader 或 Secret manifest；
- settings 只有 documented names，沒有 dotenv loading 或環境 dump；
- Docker/Kubernetes 只含 environment reference、`secretKeyRef` 與 placeholder。

掃描失敗只能列檔名、行號與規則類別，不得回印疑似 credential 的匹配文字。

## Handoff matrix

| Gate | 需要 live credential | 成功條件 |
| --- | --- | --- |
| pytest offline | 否 | Unit、contract、adapter fake 與 validation 全通過 |
| Ruff / mypy | 否 | 無 lint、型別錯誤 |
| Repository verification | 否 | Independence 與 secret-safety 通過 |
| Docker build | 否 | Frozen lock安裝成功，image沒有外部reference dependency |
| Smoke / integration | 是 | 三個外部 dependency 與兩個 LiteLLM model operation 通過 |
| 100 題 evaluation | 是 | 100 題完成並產生可比較、無 Secret 的 metrics |
| Load test | 是 | 六個 concurrency 階段有完整 metrics 與瓶頸分類 |

未能執行 live gate 時，交付報告應寫明「必要 runtime environment 未提供」與安全
命令，不將 skipped 誤報為 passed。
