# Load testing

Load test 的目的不只是找最大 RPS，而是分辨瓶頸在 FastAPI/application core、
PostgreSQL keyword retrieval、Qdrant、LiteLLM gateway，或 model backend。測試只能
在 Human Operator 核准的環境執行，且 runtime credential 必須已注入目前 process；
工具不得接受或輸出 credential 值。

## 前置條件

- Migration 與所需法規同步已完成，PostgreSQL/Qdrant projection 一致。
- `/health` 與 `/ready` 均成功，smoke test 已通過。
- 固定 image、dataset、RAG profile、prompt/model version、Top K 與測試 payload。
- 使用 checked-in 非敏感問題或合成問題，不使用 production conversation。
- 確認測試時段、允許負載、停止條件與外部 dependency quota。
- 先記錄 API replica/resources、PostgreSQL/Qdrant topology 與 LiteLLM quota 類別；
  不記錄 endpoint 或 credential 真值。

先執行：

```powershell
python scripts/smoke_test.py
```

## 固定階段

正式 scenario 依序執行 1、5、10、20、50、100 concurrent：

```powershell
python scripts/load_test.py --concurrency 1,5,10,20,50,100
```

不可從 1 直接跳到 100。每一階段使用一致的 warm-up、request count 與payload
distribution。上述固定命令預設會量完六層，即使response已出現quota/error signal也
會把它記入result；這是為了產生可比較baseline，不代表可忽略Human Operator核准的
安全停止政策。保留每階段開始/結束時間、成功/失敗數與設定fingerprint，不保留
authorization data或完整request/response body。

建議停止條件：持續高錯誤率、外部服務明確 rate limit、依賴不可用、資源飽和導致
連續 timeout、validation/citation correctness 明顯失效。停止後不要藉由顯示 header
或 Secret 來診斷。需要script自動停止時可明確加入`--stop-error-rate 0.20`和／或
`--stop-on-gateway-quota`；提前停止會產生partial report、印出FAIL並回non-zero，
不得列為六階段gate passed。CPU/memory等script看不到的安全條件由Human Operator
監控並在必要時中止process。

## 必收 metrics

每個 concurrency level 的完整 run evidence 由兩種來源組成。`load_test.py` 只保存
HTTP client實測與API response中的allowlisted stage timings；它不連cluster、讀
container runtime、資料庫系統表或gateway管理面。CPU、memory、replica、pool與外部
quota telemetry需由Human Operator在已授權的監控面另行取得，經遮罩後和相同時間窗
對照，不能假裝script已自動收集。

| 類別 | Metrics | 來源 |
| --- | --- | --- |
| Throughput | request count、success count、RPS | load script |
| End-to-end | p50、p95、p99、max latency、timeout rate、error rate | load script |
| Correctness | structured validation、citation allowlist、empty answer rate | load script（chat scenario） |
| Pipeline stages | embedding、vector、keyword、generation等API回傳的p50/p95/p99 | load script；只有成功response含有的allowlisted timing |
| Application | queue/wait、active requests、CPU、memory、replica count、5xx | operator monitoring；5xx另可由load script觀察 |
| Qdrant/PostgreSQL | service latency/error、candidate count、pool wait | operator monitoring＋API stage timing |
| Gateway/model | 429/quota、queue、token usage（若安全可得） | load response＋operator monitoring |

只記錄 allowlisted stage timing、status、model/profile metadata 與 stable provision
IDs。禁止記錄 credential、headers、DSN、完整 environment、production user content
或未過濾的 external response。

## Application capacity 與 LiteLLM quota

兩個結果不可混為一談：

1. **Application capacity**：FastAPI worker/replica、connection pool、Python work、
   PostgreSQL 與 Qdrant concurrency 能否保持穩定。
2. **Gateway/model capacity**：LiteLLM 的 parallel、RPM、TPM policy，以及模型推論
   queue/latency。

目前 brief 記錄的既有 gateway key 參考限制為 5 parallel、60 RPM、100000 TPM；
這些值可能由 Human Operator 調整，且不是 application server 的容量上限。當
concurrency 超過 5 時，model queue 或 429 很可能先主導 end-to-end latency。報告
必須標示「gateway quota/model bottleneck」，不可寫成「FastAPI 最多 5 concurrent」。

隔離判讀方式：

- 先以 `/health`／`/ready` 與 offline/in-process tests 確認 web layer 並行基礎；
- End-to-end scenario 使用真實 QA pipeline，從 spans/metrics 拆出 embedding、
  Qdrant、keyword、generation 與 total latency；
- 若 total 增長而 application CPU、pool wait、Qdrant/PostgreSQL 穩定，但 LLM
  latency/429 上升，歸類為 gateway/model；
- 若 model stage 穩定但 API queue、CPU、memory、pool wait 或 5xx 上升，歸類為
  application/dependency capacity；
- 若 Langfuse 不可用但 QA metrics 正常，記錄 observability loss；不可把它算成 QA
  failure，也不可讓 telemetry backpressure 主導結果。

## 結果格式與比較

每次 run 記錄：application version/image、profile、prompt/model identifiers、dataset
version、concurrency、stage latency percentiles、throughput、error taxonomy、external
quota 類別與測試環境摘要。環境摘要只寫 topology/資源級別，不寫 URL、credential
或 Secret source。

比較兩次結果前，確認固定項目相同；否則標為不可直接比較。100 concurrency 通過
不代表可直接成為 production limit，還需 Human Operator 決定安全 headroom、
autoscaling、rate limit 與 model quota。Load test 不自行修改 HPA、gateway quota 或
production deployment。
