# Configuration

`legal_qa_platform` 只從目前 process environment 讀取設定。應用程式與工具不載入
dotenv、不尋找 credential 檔案，也不知道 Human Operator 如何準備環境。
契約的唯一實作位於 `src/legal_qa_platform/config/settings.py`；
`.env.example` 只描述名稱與必填性，
不應填入或提交真值。

## Application runtime：13 個名稱

| 名稱 | 必填規則 | 敏感性 | 用途 |
| --- | --- | --- | --- |
| `POSTGRES_EXTERNAL_HOST` | 與 internal host 至少一個 | 一般設定 | 開發環境可達的 PostgreSQL host；只填 host，不填 DSN |
| `POSTGRES_INTERNAL_HOST` | 與 external host 至少一個 | 一般設定 | 服務網路內的 PostgreSQL host；同時存在時優先 |
| `POSTGRES_PORT` | 必填 | 一般設定 | PostgreSQL TCP port，必須介於 1 至 65535 |
| `POSTGRES_LITELLM_USER` | 必填 | credential metadata | 既有的 application identity；只執行 `legal_qa` 日常 DML/sequence usage，不執行 DDL |
| `POSTGRES_LITELLM_PASSWORD` | 必填 | Secret | PostgreSQL password，以 redacting type 保存 |
| `POSTGRES_LITELLM_DATABASE` | 必填 | credential metadata | Application target database；只能使用 application-owned schema |
| `QDRANT_PUBLIC_URL` | 與 internal HTTP URL 至少一個 | 一般設定 | 開發環境可達的 Qdrant HTTP base URL |
| `QDRANT_INTERNAL_HTTP_URL` | 與 public URL 至少一個 | 一般設定 | 服務網路內的 Qdrant HTTP base URL；同時存在時優先 |
| `QDRANT_INTERNAL_GRPC_ENDPOINT` | 選填 | 一般設定 | 預留的內部 gRPC endpoint；baseline 不要求使用 |
| `QDRANT_API_KEY` | 必填 | Secret | Qdrant runtime credential，以 redacting type 保存 |
| `LITELLM_PUBLIC_URL` | 與 internal URL 至少一個 | 一般設定 | 開發環境可達的 LiteLLM base URL |
| `LITELLM_INTERNAL_URL` | 與 public URL 至少一個 | 一般設定 | 服務網路內的 LiteLLM base URL；同時存在時優先 |
| `LITELLM_API_KEY` | 必填 | Secret | LiteLLM runtime credential，以 redacting type 保存 |

這 13 個名稱是 API、sync、smoke、evaluation 與 load test 的完整 runtime
contract。這些 process 不得接收下節的 admin names。

## Operator-only migration：3 個額外名稱

| 名稱 | 必填規則 | 敏感性 | 用途 |
| --- | --- | --- | --- |
| `POSTGRES_ADMIN_USER` | 只對 `scripts/migrate.py` 必填 | credential metadata | 顯式 one-shot migration 的 DDL identity |
| `POSTGRES_ADMIN_PASSWORD` | 只對 `scripts/migrate.py` 必填 | Secret | Admin password，以 redacting type 保存，只在 migration driver 邊界 unwrap |
| `POSTGRES_ADMIN_DATABASE` | 只對 `scripts/migrate.py` 必填 | credential metadata | Migration 目標 database；必須與 `POSTGRES_LITELLM_DATABASE` 相同 |

Migration 仍使用既有 PostgreSQL host/port，並只需 runtime
`POSTGRES_LITELLM_USER`/`POSTGRES_LITELLM_DATABASE` 作為 grant/target metadata；不使用
runtime password、Qdrant 或 LiteLLM credential。安全 preflight 若發現兩個 database names
不同，會在連線/變更前中止，只回報固定 category，不顯示 database
或 identity 的實際名稱/值。Admin 與 runtime user 必須不同；runtime role 必須已存在、
允許 login，且不可是 superuser 或具有 create-database/create-role、replication、
bypass-RLS 等管理權限。Migration
只建立/修改 `legal_qa` schema 物件並授予 runtime identity 必要的 schema、
table DML、sequence 與 database connect 權限；不建立、修改或刪除
role/database。

16 個 allowlisted names 分成兩個互不繼承的 typed settings boundary：
`RuntimeSettings` 只宣告 13 個 runtime names；`PostgresMigrationSettings` 只宣告
PostgreSQL host/port、3 個 admin names 與 runtime `USER`/`DATABASE` grant metadata。
因此 API/runtime 不會解析或保存 admin fields，migration 也不會解析 runtime
PostgreSQL password、Qdrant 或 LiteLLM Secret。
Human Operator 應在獨立的 operator process 執行 migration；完成後，API 與其他
normal runtime processes 只注入上述 13 個 names。

空字串會被正規化為未設定。名稱大小寫敏感；除上述 16 個 allowlisted
names 外，其他環境變數不會成為專案設定，也不可用來偷偷增加行為開關。

## Endpoint 選擇

同一份 source 與 image 適用於開發和部署環境：

| Dependency | 服務網路內 | 開發／外部連線 | 選擇規則 |
| --- | --- | --- | --- |
| PostgreSQL | `POSTGRES_INTERNAL_HOST` | `POSTGRES_EXTERNAL_HOST` | internal 優先，external fallback；共用 `POSTGRES_PORT` |
| Qdrant | `QDRANT_INTERNAL_HTTP_URL` | `QDRANT_PUBLIC_URL` | internal 優先，public fallback |
| LiteLLM | `LITELLM_INTERNAL_URL` | `LITELLM_PUBLIC_URL` | internal 優先，public fallback |

Domain 與 service layer 不知道選到了哪一類 endpoint。URL 不得包含 user、
password、API key 或其他 credential；credential 由獨立的 Secret 欄位傳入
adapter。

`scripts/migrate.py` 另支援 `--endpoint-scope auto|public|internal`；這個 argument
只從已文件化的 PostgreSQL host fields 選擇 family，不接受 endpoint 或
credential 值。`auto` 保留 internal-first precedence。

目前 `compose.yaml` 以 external/public 欄位作為本機容器可達的必要入口，
internal 欄位為選填；Kubernetes ConfigMap 範本則使用 internal 欄位。兩者都
只引用相同的 13-name runtime contract；正常 API/UI deployment 不引用
`POSTGRES_ADMIN_*`。

## Repository-owned runtime assets

`data/` 與 `profiles/` 不是 credential 或 environment configuration。Default loader
以 process working directory 為 root，因此啟動 API、同步或 evaluation 時，working
directory 必須是包含這兩個目錄的 repository/runtime root。Local command 從 repository
root 執行；Dockerfile 把它們複製到 `/app/data`、`/app/profiles` 並固定
`WORKDIR /app`。Scripts/composition 可以傳入明確 `Path`，但不得回退到 reference
repository 或搜尋其他目錄。

缺少 asset 時只回報 repository-relative filename；不要把任意 host path、目錄 listing
或環境內容放入 error/log。Profile 是 checked-in、versioned JSON，不以額外 environment
knob 覆寫。

## 驗證與安全狀態

`RuntimeSettings.require_runtime()` 在組合 live adapter 前驗證必要名稱。錯誤
只列缺少的名稱，不列值或完整 settings。`safe_status()` 只回報 endpoint 類型
與 credential 是否存在，不回報 endpoint 或 credential 內容。

應用程式不得自動補猜缺失值。缺少設定時，Human Operator 應在啟動 process
之前完成環境注入，之後直接執行安全的 smoke test：

```powershell
python scripts/smoke_test.py
```

不要把 Secret 放在 command-line argument、source、測試 fixture、Docker
build argument 或 repository 內的設定檔。

## Streamlit

Streamlit API 位址不是新的環境變數。UI 必須透過 `--api-base-url` CLI argument
連到 REST API，例如本機開發：

```powershell
python -m streamlit run src/legal_qa_platform/ui/streamlit_app.py -- --api-base-url http://127.0.0.1:8000
```

Compose 與 Kubernetes 範本也使用此 argument，把 UI 指向各自的 API service。
UI 不直接 import QA service。

## HTTP transport environment boundary

專案自行建立的 LiteLLM、Qdrant、Streamlit 與 load-test HTTP clients 明確設定
`trust_env=False`。連線路由只能由上述 runtime contract 的 endpoint 或已記錄的
`--api-base-url`決定，不會隱式套用HTTPX支援的system proxy、`NO_PROXY`或TLS
certificate environment設定。這可避免規格外environment variable在不同terminal、
service或container中暗中改變production behavior。

若部署環境確實需要 HTTP proxy 或自訂 CA，必須先把所需設定正式加入 allowlisted
configuration contract、deployment references、安全文件與測試；不得依賴 HTTP
library 自動讀取未記錄的 process environment。

## Langfuse

目前 13-name runtime contract 沒有 Langfuse configuration，因此預設使用
no-op observability。即使安裝 optional observability dependency，預設 composition
仍不會自行探查或推測設定。Langfuse 未設定或不可用時，QA 必須繼續服務。

日後若 Human Operator 核准擴充 contract，需同時更新 settings、範例、Docker、
Kubernetes references、安全測試與本文件；在此之前維持 disabled、fail-open。
