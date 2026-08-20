# Security and secrets

本專案的安全邊界是 process environment。Human Operator 負責在 process 啟動前
準備 runtime credential；應用程式與開發工具只知道
[configuration contract](configuration.md) 的名稱，不知道值的保存位置、載入方式
或平台的管理流程。

## 必須維持的邊界

- 不搜尋、讀取或推測 `.env`、credential 檔案、Secret 目錄、shell profile、
  credential store、載入 script 或 repository 外部的 Secret 管理資料。
- 不要求 Human Operator 貼上 API key、password、token、private key、master key、
  administrator credential、kubeconfig 或 Kubernetes Secret。
- 不 dump process environment、settings、request headers、cookies 或外部服務的
  原始 error response。
- Smoke test 不接受 credential command-line flags 或 Secret file argument；只讀
  已存在的 process environment。
- 缺少必要設定時只列變數名稱，提供安全測試命令，不嘗試自行尋找替代來源。
- 所有 deployment artifacts 僅含 environment reference、`secretKeyRef` 或明確
  placeholder，不含 Secret 真值。

## 程式內 credential lifecycle

1. Settings layer 只宣告 allowlisted contract，關閉 dotenv 載入。
2. Password 與 API key 使用 `SecretStr` 等 redacting type；domain entity 不得持有。
3. 只有真正發出 PostgreSQL、Qdrant 或 LiteLLM 呼叫的 adapter 能在最後一刻
   unwrap 所需值。
4. Exception 必須轉成 service、status、error category 等安全資訊，不附 response
   body、header、DSN 或 credential-bearing URL。
5. Object representation、health/readiness、test assertion 與 trace 都要驗證不會
   洩漏敏感值。
6. Repository-owned HTTP clients 必須停用隱式 environment trust；系統 proxy、
   `NO_PROXY`與TLS certificate environment不是目前allowlisted runtime contract，
   不得暗中成為連線或credential來源。

資料庫身分只能視為 development-time existing credential，不得假設具有
superuser、database administrator 或 cluster administrator 權限。Migration 只能
操作 application-owned schema，不可修改或刪除無關的 LiteLLM table。權限不足時
回報缺少的 operation，由 Human Operator 處理；不得要求提升 credential。

## Log、error 與 telemetry allowlist

可以記錄：

- service 與 pipeline stage 名稱；
- HTTP status、exception type、timeout duration 與 latency；
- model name、embedding dimension、profile、prompt version；
- question／normalized-question 的hash與length，不記錄原文；
- candidate count、Top K、stable `provision_id`、score 與 validation result；
- credential 是否存在的 boolean，以及 endpoint 類型為 internal、public 或 missing。

不得記錄：

- API key、password、token、cookie、authorization header、private key；
- 完整 settings、完整 environment、credential-bearing DSN 或 URL；
- 外部服務未過濾的 response body 或 exception representation；
- 未經核准的 student identity、conversation、question、answer、prompt 或完整 RAG
  context。

PostgreSQL的application-owned `qa_runs`、conversations與messages會保存其schema明定的
question/validated response內容，這是durable product data，不是可任意複製的operational
log或trace。其access、retention與deletion政策在正式學生服務前仍需Human Operator／
資料治理者核准；在此之前不得把內容再送往console、Langfuse或其他診斷系統。

Langfuse 目前因 configuration contract 未擴充而預設停用。未來啟用時仍只能送出
allowlisted metadata；SDK、network 或 flush 失敗一律 fail-open，不得讓成功的 QA
response 失敗。Langfuse 不是 conversation 或 audit source of truth。

## Docker 與 Kubernetes

- Image build context 不包含 credential 檔案，Dockerfile 不接受真實 credential 的
  build argument，也不把 runtime Secret 寫入 image layer。
- Compose 只轉交 Human Operator 已注入目前 process 的名稱；執行
  `docker compose config`、container inspect 或診斷工具前要確認不會顯示解析後的
  credential。
- Kubernetes templates 沒有 Secret manifest，也沒有 namespace 真值。API
  Deployment 只保留 `secretKeyRef` placeholder；正式 reference 與 provisioning
  完全由 Human Operator 管理。
- 不讀取、describe、decode 或匯出 cluster Secret，也不尋找 kubeconfig 或要求
  cluster-admin 權限。
- Container 以 non-root、drop capabilities、no-new-privileges 執行；Kubernetes
  template 另使用 read-only root filesystem 與專用暫存 volume。

## 測試與 review gate

離線安全與獨立性檢查不需要 credential：

```powershell
python scripts/verify_repository.py
python -m pytest
```

Verification 應以「檔案、規則類別、結果」回報，不印出疑似 Secret 的匹配內容。
Live smoke test 只在必要 runtime names 已由 Human Operator 注入時執行：

```powershell
python scripts/smoke_test.py
```

若發現可能洩漏，停止複製或散布原始輸出，僅保留已遮罩的事件資訊並通知 Human
Operator 依既有程序處置。不要把疑似值貼到 issue、commit、chat 或 trace。

交付前確認：

- tracked files 沒有真實 credential 或 credential loader；
- error、logging、health 與 test output 有 allowlist／redaction 測試；
- Docker image 與 Kubernetes templates 只有 references/placeholders；
- live 測試的缺設定路徑只報名稱，不要求值；
- 正式 repository 可在唯讀參考 repository 不存在時獨立 build、test 與執行。
