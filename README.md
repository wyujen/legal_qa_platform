# legal_qa_platform

以 Python 實作的繁體中文法規 RAG application。PostgreSQL 保存法規 master data、
keyword retrieval、runs 與 conversation；Qdrant 保存 `bge-m3` 1024 維向量；
LiteLLM REST 提供 `bge-m3` embedding 與 `campus-qa` generation。Streamlit 只透過
FastAPI REST 使用同一套 retrieval、prompt 與 validation core。

Baseline 保留 stable `provision_id`、content/embedding hash、full/partial sync、
hybrid retrieval、Top K、context extraction、structured output、citation allowlist 與
100 題 evaluation；不使用 reranker、Redis、pgvector runtime vectors 或舊 NPY flow。

## Quickstart

需要 Python 3.11+，以及由 Human Operator 準備的外部 PostgreSQL、Qdrant 與
LiteLLM。所有命令都從本 repository root 執行；default loaders 以目前 working
directory 解析 `data/` 與 `profiles/`。

先完成離線安裝與驗證：

```powershell
python -m pip install -e ".[dev,ui,observability]"
python -m pytest
python -m ruff check .
python -m mypy
python scripts/verify_repository.py
```

Domain/API contract變更時，以`python scripts/export_schemas.py`更新checked-in
`schemas/`，再重跑上述gate。

Live operation 只讀目前 process environment 中的
[allowlisted configuration contract](docs/configuration.md)，共 13 個 application
runtime names。Application 不載入 dotenv；不要把credential 放入 command line、
repository 或測試輸出。專案不讀取 database administrator credential。

建立 application schema 前，先離線驗證 repository SQL：

```powershell
python scripts/migrate.py
```

這個命令只驗證並列出 DBeaver handoff，不連線、也不套用 database migration。
Human Operator 在 DBeaver 以既有管理連線選定正確 database，開啟
`migrations/0001_initial.sql`，使用 **Execute SQL Script** 執行整份檔案；看到
`COMMIT` 後再執行 `migrations/checks/0001_initial_readonly.sql`，所有 `passed`
必須為 `true`。SQL 不含 role/user/database 或 grant；runtime identity 的最小權限
由 Human Operator 在 DBeaver 權限介面設定。完整步驟見
[database guide](docs/database.md#dbeaver-manual-ddl-workflow)。

完成 DDL 與權限設定後，在 runtime process 注入 13 個 runtime names 再執行：

```powershell
python scripts/smoke_test.py --phase dependencies
python scripts/sync_laws.py --mode full-snapshot
python scripts/smoke_test.py --phase full
python -m legal_qa_platform.api.server --host 0.0.0.0 --port 8000
```

`dependencies` 可在資料同步前驗證 PostgreSQL schema、Qdrant service，以及
LiteLLM readiness、embedding 與 structured chat；它會明確略過尚待 bootstrap 的
published snapshot 與 Qdrant collection。`full` 是預設值，資料同步後仍會嚴格驗證
這兩項資料契約。

本機若同時有 internal/external host，但只能連 external/public family，smoke、sync
與 API command 都可明確使用 `--endpoint-scope public`。這個 option只選擇已文件化
的 endpoint family，不接受 URL 或 credential，也不修改 process environment。
離線 migration validator 沒有 endpoint option。

`full-snapshot` 僅適用完整權威資料；一般修補使用
`python scripts/sync_laws.py --mode partial`。`GET /health` 是 process liveness；
`GET /ready` 會檢查 PostgreSQL application schema與成功發布的snapshot、Qdrant
service與profile指定的collection/dimension，以及LiteLLM gateway。

另開 process 啟動 MVP UI：

```powershell
python -m streamlit run src/legal_qa_platform/ui/streamlit_app.py -- --api-base-url http://127.0.0.1:8000
```

Evaluation 與漸進 load test：

```powershell
python scripts/evaluate.py
python scripts/load_test.py --concurrency 1,5,10,20,50,100
```

Docker image 只包含 application；external services 與真實 deployment values 不會被
打包：

```powershell
docker compose build
docker compose run --rm api python scripts/sync_laws.py --mode full-snapshot
docker compose up --detach
```

Database DDL 不由 container 或 API startup 自動執行；Human Operator 先完成上述
DBeaver workflow。Compose 只接收 13-name runtime contract。同步時機與
`full-snapshot`適用性仍由 Human Operator確認。

## Architecture and safety

- FastAPI entry point：`legal_qa_platform.api.app:app`。
- Versioned baseline profile：`profiles/platform-baseline-v1.json`；prompt identifier
  為 `legal_qa_platform-prompt-v1`。
- PostgreSQL 是 legal/conversation source of truth；Qdrant 是可重建的 vector
  projection。跨 store 以 generation、hash、idempotent upsert 與 retrieval-time
  revalidation 維持一致性。
- Model output 一律視為不可信，必須通過 strict JSON、structured validation、plain
  text cleanup 與 citation allowlist。
- Langfuse adapter 為 fail-open；目前 environment contract 未擴充，因此預設 no-op，
  不影響 QA readiness 或結果。
- Runtime credential 僅由 Human Operator 透過 environment variables 注入。不可搜尋、
  顯示、記錄或提交真實 Secret；Docker/Kubernetes 只保留 references/placeholders。

## Documentation

從 [documentation map](docs/README.md) 開始；常用入口：

- [Architecture](docs/architecture.md) 與 [end-to-end data flow](docs/data_flow.md)
- [Ingestion](docs/ingestion.md)、[retrieval](docs/retrieval.md)、
  [context/prompt](docs/context_and_prompt.md) 與 [validation](docs/validation.md)
- [API](docs/api.md)、[database](docs/database.md)、
  [conversation](docs/conversation.md) 與 [observability](docs/observability.md)
- [Configuration](docs/configuration.md)、
  [security/secrets](docs/security_and_secrets.md) 與 [deployment](docs/deployment.md)
- [Testing](docs/testing.md)、[load testing](docs/load_testing.md) 與
  [troubleshooting](docs/troubleshooting.md)
- [Reference migration inventory](docs/reference_migration.md) 與
  [architecture decisions](docs/adr/README.md)
