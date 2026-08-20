# Deployment

`legal_qa_platform` 的 application image 只包含 API、UI 所需程式與 checked-in
data。PostgreSQL、Qdrant、LiteLLM、Langfuse 與模型服務都是外部 dependency，不會
被 build 進 image，也不由 `compose.yaml` 或 Kubernetes templates 建立。

部署前先閱讀 [configuration](configuration.md) 與
[security boundary](security_and_secrets.md)。Human Operator 必須在啟動 process
前準備 runtime environment；本文件不定義 Secret 保存、載入、provisioning、真實
endpoint、namespace 或 cluster credential。

## 本機 Python 啟動

下列命令都從同時含有 `data/` 與 `profiles/` 的 repository root 執行。Default
loader以目前 process working directory解析這些versioned assets，不會搜尋其他路徑。

先安裝 application，並離線驗證 manual DDL bundle：

```powershell
python -m pip install -e ".[dev,ui,observability]"
python scripts/migrate.py
```

Validator 不讀 environment、不連線、不套用 migration。Human Operator 接著依
[DBeaver manual DDL workflow](database.md#dbeaver-manual-ddl-workflow) 在正確 target
database 執行 `migrations/0001_initial.sql`、執行 read-only post-check，並透過 DBeaver
權限介面設定既有 runtime identity。完成後，以只含 13 個 runtime names 的 process
執行：

```powershell
python scripts/sync_laws.py --mode full-snapshot
python -m legal_qa_platform.api.server --host 0.0.0.0 --port 8000
```

如果 workstation runtime process 同時注入 internal 與 external/public endpoints，
可為 smoke、sync 與 API server 指定相同的 `--endpoint-scope`。離線 migration
validator 沒有 endpoint 或 credential option。例如需使用 external/public endpoints：

```powershell
python scripts/smoke_test.py --endpoint-scope public --phase dependencies
python scripts/sync_laws.py --mode full-snapshot --endpoint-scope public
python -m legal_qa_platform.api.server --endpoint-scope public --host 0.0.0.0 --port 8000
```

每個 command 都獨立從當前 process 建立 immutable settings；不需要也不會修改
environment。若同一個 process 同時具有兩組 endpoints，請在這些命令使用
相同的 explicit scope，避免 bootstrap 與 web process 連到不同的 service family。

`full-snapshot` 只能用於完整權威資料；增量資料使用：

```powershell
python scripts/sync_laws.py --mode partial
```

Manual DDL 與 synchronization 都是顯式、可重跑的 operation，不在 web process
startup 中暗自執行。Repository SQL 只操作 application-owned schema；DBeaver 管理
連線由 Human Operator 管理，專案不讀取其 credential。

API checks：

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health
Invoke-WebRequest http://127.0.0.1:8000/ready
```

`/health` 表示 application process 可回應；`/ready` 另外確認PostgreSQL application
schema與成功published snapshot、Qdrant service與profile collection/dimension，以及
LiteLLM gateway。Langfuse 停用或故障不得使 readiness 或 QA 失敗。

另開 process 啟動 Streamlit HTTP client：

```powershell
python -m streamlit run src/legal_qa_platform/ui/streamlit_app.py -- --api-base-url http://127.0.0.1:8000
```

## Docker image

```powershell
docker build --tag legal_qa_platform:local .
```

目前 Dockerfile 使用 multi-stage Python 3.12 slim build，以固定版本的 `uv` 和
checked-in `uv.lock --frozen` 安裝 production、UI與observability extras；runtime使用
non-root UID/GID 10001、`WORKDIR /app`、checked-in `/app/data`與`/app/profiles`、
application-owned `/app/scripts`與`/app/migrations`、port 8000與`/health` image
healthcheck。Image不包含runtime credential、Secret loader、資料庫、vector store、
gateway或observability server。

DDL 與同步不會在 API container startup 自動執行。DDL 必須先由 Human Operator
從 checked-in repository SQL 完成 DBeaver workflow；application container 不接收
administrator credential。確認外部服務、runtime environment 與 snapshot 語意後，
可用 image 執行同步：

```powershell
docker compose run --rm api python scripts/sync_laws.py --mode full-snapshot
```

這個命令只有在 input 是完整權威 snapshot 時才可使用；一般修補改用
`--mode partial`。Compose 只引用 13-name runtime contract。執行與 rollback 時機由
Human Operator 決定；不得把 DDL 或 sync 綁入每個 API replica 的 concurrent startup。

在 Human Operator 已準備目前 process environment 後，啟動 API 與 UI：

```powershell
docker compose up --build --detach
docker compose ps
```

Compose 對 host 僅綁定 loopback：API `127.0.0.1:8000`、UI
`127.0.0.1:8501`。UI 透過 `--api-base-url http://api:8000` 連到 API；它沒有額外的
environment setting。API container 直接使用外部 PostgreSQL、Qdrant 與 LiteLLM。

停止 application containers：

```powershell
docker compose down
```

Compose 不建立或刪除 external dependencies。不要使用可能顯示已解析 environment
內容的 inspect/config output 作為一般診斷，也不要把其輸出貼入 issue 或 chat。

## Kubernetes templates

`deploy/kubernetes/` 是可審查範本，不是可直接套用的 production values：

| 檔案 | 責任 |
| --- | --- |
| `configmap.yaml` | internal PostgreSQL/Qdrant/LiteLLM endpoint placeholders 與 port |
| `api-deployment.yaml` | API replicas、ConfigMap reference、credential `secretKeyRef` placeholders、probes 與 security context |
| `api-service.yaml` | API ClusterIP service |
| `ui-deployment.yaml` | Streamlit 與 API service 的 CLI URL、probes 與 security context |
| `ui-service.yaml` | UI ClusterIP service |
| `ingress.yaml` | host、TLS reference 與 ingress class placeholders |
| `hpa.yaml` | API CPU-based 2 至 10 replicas 範本 |

範本刻意沒有：

- Secret manifest 或 Secret 真值；
- namespace 真值；
- production image reference、host、TLS Secret reference 或 ingress class 真值；
- PostgreSQL、Qdrant、LiteLLM、Langfuse 或模型 workload；
- cluster-specific storage、network policy、identity 或 certificate 決策。

Human Operator 在 repository 外或核准的 deployment pipeline 中完成 placeholder
rendering、選擇 namespace、建立/引用 Secret、設定 image 與套用 manifests。正式
apply 前應先在其授權環境做 schema validation／dry run；Codex 不讀 kubeconfig、
不查詢或 decode Secret，也不要求 cluster-admin 權限。

API Deployment 只引用 13 個 runtime names。Baseline 不提供 Kubernetes migration
Job；application workload 不執行 DDL。Human Operator 必須在部署 workload 前完成
DBeaver manual workflow，且 administrator credential 不進入 manifests 或 pods。

API pods 使用 startup `/health`、readiness `/ready`、liveness `/health`。Pod 與
container 設為 non-root、停用 service-account token 自動掛載、drop all
capabilities、禁止 privilege escalation、使用 RuntimeDefault seccomp 與 read-only
root filesystem。API 只保留 `/tmp` 的 ephemeral volume；Streamlit 另有 ephemeral
home volume，兩者都不保存 application state。

HPA 需要 cluster metrics 支援，其 max replicas 也不代表 LiteLLM/model concurrency
會同步增加。部署前必須依 [load-testing plan](load_testing.md) 區分 application
capacity 與外部 gateway quota。

## Deployment sequence

1. 建立 immutable image reference，並完成 offline test、verification 與 image scan。
2. Human Operator 準備 external services、runtime references 與 deployment values。
3. 執行 offline migration validator；Human Operator 依 DBeaver workflow 執行完整
   repository SQL、read-only post-check，並在 GUI 設定 runtime 最小權限。
4. 以 runtime identity 執行 `smoke_test.py --phase dependencies`。
5. 以 `partial` 或經確認的 `full-snapshot` 同步法規，驗證 Qdrant 1024-dimensional
   collection/projection。
6. 確認 API 只引用 13-name runtime contract，再部署 API，確認 `/health` 與
   `/ready`；再部署 UI/Ingress。
7. 執行 `python scripts/smoke_test.py --phase full` 與 `python scripts/evaluate.py`。
8. 依 1、5、10、20、50、100 concurrency 漸進 load test，再決定 replica 與
   resource settings。

Rollback 應切回已驗證的 immutable application image。資料 migration 與完整快照
不得因 image rollback 自動做破壞性反向操作；需要資料修復時先保留 run evidence，
依 application-owned migration/sync policy 處理。
