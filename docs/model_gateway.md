# LiteLLM Model Gateway

`legal_qa_platform` 不直接連接模型 runtime。`LiteLLMGateway` 同時實作 application-owned `EmbeddingProvider` 與 `ChatModel` port，經 OpenAI-compatible REST 使用 `bge-m3` 與 `campus-qa`。Domain/service 不知道後端是 Xinference、vLLM、外部 provider 或其他 inference server。

## Embedding call

```text
POST <resolved LiteLLM endpoint>/v1/embeddings
Authorization: Bearer <runtime-injected credential>

{"model": "bge-m3", "input": ["..."]}
```

Adapter input 是 non-empty strings、model name 與 expected dimension。Output 依 response index 排序，且必須與 input count 相同；每個 vector 恰為 1024 個有限浮點數。Count、index、type 或 dimension 不符都轉成安全的 `ExternalServiceError` category，不附 response body 或 header。

Query embedding 與 ingestion embedding 共用同一 port/validation；不可因呼叫來源不同而跳過維度檢查。

## Chat call

```text
POST <resolved LiteLLM endpoint>/v1/chat/completions
Authorization: Bearer <runtime-injected credential>

{
  "model": "campus-qa",
  "messages": ["<provider-neutral messages>"],
  "max_tokens": 1200,
  "temperature": 0,
  "response_format": {"type": "json_schema", "json_schema": "<contract>"}
}
```

`max_tokens` 是必填：目前 `campus-qa` 底層 adapter 在缺少它時可能回 HTTP 500。Profile 必須提供正整數，adapter 亦再次驗證。`temperature=0` 提高 baseline 可重現性；仍不能假設模型輸出一定合法。

Adapter 只抽出第一個 non-empty assistant content、response model/request ID 與整數 usage metadata。完整 provider payload、response body、headers 和 authorization material 不會傳入 domain/log/trace。

## Endpoint resolution

Settings 只讀文件化的 process environment names：

- Kubernetes/server 優先 `LITELLM_INTERNAL_URL`；
- development fallback `LITELLM_PUBLIC_URL`；
- credential 為 `LITELLM_API_KEY`。

兩個 endpoint 都存在時選 internal；兩者皆無或 credential 缺少時 fail fast，只回報缺少的 variable name。Application 不知道變數如何被 Human Operator 注入，也不讀任何 credential file。

## Errors 與 retry boundary

HTTP status、timeout/error type、service name、model name與 latency 可以被安全記錄；URL query、header、response body、request messages 與 credential 不可自動寫入 exception。Adapter 將 transport/status/shape 問題分類，QA service 決定是否重試或回傳 unavailable。

Baseline adapter不做transport retry。QA service只對第一次不符合structured schema的chat output允許一次repair completion；它不是網路錯誤重試。日後若加入transport retry，僅限明確transient error、短exponential backoff、有總deadline，且chat retry必須處理重複請求/成本。輸入或dimension錯誤不可重試。

## Readiness 與 smoke test

Readiness 可呼叫 LiteLLM `/health/readiness`，但 endpoint healthy 不代表指定模型可用。安全 smoke test另驗證：

- `bge-m3` 回傳 1024 維；
- `campus-qa` 在有 `max_tokens` 時回傳 completion；
- 失敗輸出只有 PASS/FAIL、status/category/model/dimension/latency。

由 Human Operator 先把 runtime variables 注入目前 process，再執行 `python scripts/smoke_test.py`。Script 不接受 `--api-key` 或 secret-file flags，也不列出環境內容。

## 替換 provider

新增 provider 時實作相同 `EmbeddingProvider`/`ChatModel` contract，保留 response-schema、dimension與安全錯誤測試，再由 composition root選擇；不要在 QA service 散落 provider URL或分支。Rerank port 尚未進 baseline，即使 LiteLLM 已提供 rerank endpoint也不得隱性呼叫。
