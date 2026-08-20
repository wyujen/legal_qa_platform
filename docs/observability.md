# Observability

Observability 透過 application-owned `Observability`/`Trace`/`Span` port 注入 QA service。預設 `NoopObservability` 不做 I/O；可選 `LangfuseObservability` 包住已由部署層配置完成的 client。任何建立、更新或結束 span 的例外都被 adapter 捕捉，不能改變 QA result。

## Trace shape

一題 QA 至少預留下列 spans：

```text
legal_qa_request
├─ normalize
├─ conversation_context
├─ embedding
├─ vector_retrieval
├─ keyword_retrieval
├─ hybrid_ranking
├─ context_build
├─ generation
├─ response_validation
└─ citation_validation
```

Ingestion 可另建 `legal_qa.ingestion` trace，包含 validation、hash comparison、embedding、PostgreSQL upsert、Qdrant upsert 與 reconciliation。Span name/version 應穩定，方便 evaluation/load result 對照。

## Metadata allowlist

可記錄：

- request/query/trace correlation ID；
- question/normalized-question 的 SHA-256 與字數（不含原文）；
- model/embedding model、prompt/profile/vector collection version；
- candidate K、Top K、weights、threshold、candidate count；
- `provision_id`、rank 與 retrieval scores；
- input/output count、embedding dimension；
- latency、HTTP status class、validation result與安全 error category。

不得記錄：API key、password、Authorization/Cookie/header、credential-bearing DSN/URL、settings dump、完整環境、private key 或其他 platform Secret。正式學生個資、完整 conversation/prompt/answer 的保存與 retention 尚未定案；baseline trace 應採 metadata allowlist，不預設上傳完整內容。

## Fail-open 行為

- Noop 與 Langfuse adapter 提供相同 context-manager contract。
- Span start/update/end/flush 失敗只產生不含 payload 的 warning category。
- Observability timeout/queue 不得延長 QA critical path；必要時非同步/有界 flush。
- QA service exception 仍由原層處理；observability adapter 不吞掉 application exception。
- `/ready` 不把 Langfuse 狀態列為必要條件。

此決策詳見 [ADR-0005](adr/0005-langfuse-fail-open-observability.md)。

## 目前 configuration boundary

核准的 environment-variable contract 尚未包含任何 Langfuse endpoint或credential names，因此 composition root預設使用 `NoopObservability`。Repository 內已有可注入的 Langfuse adapter與 optional dependency，但不自行發明變數、不尋找設定，也不把 credential放入 Docker/Kubernetes template。

Human Operator日後擴充正式 contract後，才在 composition layer建立 client並注入；不需修改 QA domain/service。這是明確的 unresolved deployment boundary，不是把 Langfuse變成 hard dependency的理由。

## 如何驗證

- Unit：Noop contract；fake client在 start/update/end各階段丟例外時，QA結果仍相同。
- Metadata safety：遞迴檢查 trace payload只含 allowlist keys，敏感 key/name一律拒絕或 redact。
- Integration（contract擴充後）：追一題確認各 spans、latency/profile/IDs；再中斷 exporter確認 QA仍成功。
- Load：分別比較 observability disabled/enabled，確認 exporter不造成無界 queue 或顯著 tail latency。

調查缺少 trace時先查 adapter safe warning與 configuration state，不要求、顯示或追查任何 credential。
