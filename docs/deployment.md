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

先由 Human Operator 在獨立的 one-shot migration process 注入已文件化的
PostgreSQL host/port、admin names 與 runtime `USER`/`DATABASE` grant metadata，再執行：

```powershell
python -m pip install -e ".[dev,ui,observability]"
python scripts/migrate.py
```

Migration 會要求 admin/runtime database 相同，只建立 `legal_qa` schema
物件與 runtime grants，不建立/修改 role 或 database。不要把任何真值放在
command line。Migration 完成後，另以只含 13 個 runtime names、不含
`POSTGRES_ADMIN_*` 的 process 執行：

```powershell
python scripts/sync_laws.py --mode full-snapshot
python -m legal_qa_platform.api.server --host 0.0.0.0 --port 8000
```

如果 operator workstation 只能使用 external PostgreSQL host，而目前 process 同時
注入 internal host，可在 migration command 加上 `--endpoint-scope public`。部署網路內
可使用 `--endpoint-scope internal`；不接受 URL/credential argument。同一 option 也
適用於 sync、smoke 與 API server。例如 Human Operator 在工作站需完整使用
external/public endpoints：

```powershell
python scripts/migrate.py --endpoint-scope public
python scripts/smoke_test.py --endpoint-scope public --phase dependencies
python scripts/sync_laws.py --mode full-snapshot --endpoint-scope public
python -m legal_qa_platform.api.server --endpoint-scope public --host 0.0.0.0 --port 8000
```

每個 command 都獨立從當前 process 建立 immutable settings；不需要也不會修改
environment。若同一個 process 同時具有兩組 endpoints，請在這些命令使用
相同的 explicit scope，避免 migration、bootstrap 與 web process 連到不同的
service family。

`full-snapshot` 只能用於完整權威資料；增量資料使用：

```powershell
python scripts/sync_laws.py --mode partial
```

Migration 與 synchronization 都是顯式、可重跑的 operation，不在 web process
startup 中暗自執行。Migration 只操作 application-owned schema，且 admin
credential 只存在 operator-controlled one-shot process。

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

Migration與同步不會在API container startup自動執行。Human Operator確認外部服務、
目前process environment、執行時機與snapshot語意後，可用同一immutable image做
one-shot operation：

```powershell
docker run --rm --init `
  --env POSTGRES_EXTERNAL_HOST `
  --env POSTGRES_INTERNAL_HOST `
  --env POSTGRES_PORT `
  --env POSTGRES_ADMIN_USER `
  --env POSTGRES_ADMIN_PASSWORD `
  --env POSTGRES_ADMIN_DATABASE `
  --env POSTGRES_LITELLM_USER `
  --env POSTGRES_LITELLM_DATABASE `
  legal_qa_platform:local python scripts/migrate.py
docker compose run --rm api python scripts/sync_laws.py --mode full-snapshot
```

第二個命令只有在input是完整權威snapshot時才可使用；一般修補改用`--mode partial`。
Migration command 以 `docker run` 明確建立 operator-only container；
`--env NAME` 只從 Human Operator 已注入的 host process 轉交必要 names，
不可改成 `--env NAME=value`。命令刻意不傳 runtime PostgreSQL password、
Qdrant 或 LiteLLM credential。Admin names 只出現在 one-shot container，
`compose.yaml` 的 API runtime environment 沒有引用它們。
One-shot command 不接受 password/value flags，也不把 Secret 或解析後的
Compose config寫入命令／文件。執行與rollback時機由Human Operator決定；
不得把migration/sync綁入每個API replica的concurrent startup。

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

API Deployment 只引用 13 個 runtime names，刻意不包含
`POSTGRES_ADMIN_*`。Kubernetes migration Job 不在 baseline templates 內；若平台採用
one-shot Job，Human Operator 必須在 repository 外的核准 pipeline 限時注入 admin
references，且不能讓 API pod 繼承。

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
3. 在獨立 one-shot process 以 admin identity 對匹配的 target database 執行
   migration，建立 `legal_qa` 物件並授予 runtime identity 最小權限。
4. 以 `partial` 或經確認的 `full-snapshot` 同步法規，驗證 Qdrant 1024-dimensional
   collection/projection。
5. 確認 API runtime references 不含 `POSTGRES_ADMIN_*`，再部署 API，確認
   `/health` 與 `/ready`；再部署 UI/Ingress。
6. 執行 `python scripts/smoke_test.py` 與 `python scripts/evaluate.py`。
7. 依 1、5、10、20、50、100 concurrency 漸進 load test，再決定 replica 與
   resource settings。

Rollback 應切回已驗證的 immutable application image。資料 migration 與完整快照
不得因 image rollback 自動做破壞性反向操作；需要資料修復時先保留 run evidence，
依 application-owned migration/sync policy 處理。
