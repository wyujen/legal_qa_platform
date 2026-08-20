# Conversation

Conversation persistence由 `legal_qa_platform` 控制並存於 PostgreSQL。Langfuse、n8n、Streamlit session state或未來 framework memory都不是永久 source of truth。設計決策見 [ADR-0007](adr/0007-postgresql-conversation-source-of-truth.md)。

## Baseline model

```text
conversation
  conversation_id (UUID)
  optional user_id
  status: active | closed
  created_at / updated_at

message
  message_id (UUID)
  conversation_id
  role: user | assistant | system
  content
  optional query_id
  created_at
```

Baseline context strategy是「最近 N 則訊息 + 本次 RAG context」，profile預設 N=6。讀取按 `created_at` 和 stable message ID deterministic排序；先在database取最近 N，再恢復chronological order送入prompt。

## Conversation context vs RAG context

- Conversation context：幫助理解「它」「上一條」「那個期限」等續問，可能含錯誤或使用者自行提供的內容。
- RAG context：本次經vector+keyword hybrid retrieval命中的current provisions，是citation的唯一allowlist。

Conversation曾出現ProvisionId或法條文字不能直接支持新回答。每一turn都必須重新retrieval並validation。

## Request lifecycle

1. API接收optional `conversation_id`與current message。
2. Conversation service驗證identity/status並讀取bounded history。
3. QA pipeline將history作為untrusted context，對current question執行完整RAG。
4. User message、QA run與assistant message目前各由獨立database operation保存；assistant只保存已驗證的compact response。失敗可能留下user-only turn，必須以query/error category辨識，不宣稱整個turn具單一transaction原子性。
5. API回傳conversation/query identity與已驗證answer。

未提供ID時application建立conversation；提供ID時必須是既有且active的UUID，不會隱式建立或重新開啟closed conversation。Conversation owner驗證仍待正式身份政策；不能用知道UUID本身當authorization。

## Privacy/security boundary

正式student SSO、user mapping、retention、deletion、export與moderation政策尚未定案。Baseline不得推測：

- 不把conversation內容預設送進Langfuse；
- 不用user name/email當trace ID或metric label；
- 不在error/log顯示完整message；
- 不建立長期semantic memory或Redis copy；
- 不自動設定正式retention interval。

Production開放前必須由Human Operator/資料治理者決定身份授權與生命週期，再以可審查migration/service policy加入。

## Concurrency

同一conversation可能收到並行requests。每次append有自己的transaction，讀取以timestamp/ID deterministic排序；baseline尚未提供整個turn的strict serialization或client retry idempotency。若產品要求strict turn order，再加入optimistic version、idempotency key或conversation-level lock，不使用process-local lock當多replica保證。

API server本身無session affinity需求；任何replica都從PostgreSQL載入history。Redis baseline不用。

## Failure modes/tests

- Unknown/closed conversation：typed domain error，不建立隱性第二筆。
- Message persist失敗：不可宣稱整個turn原子保存；測試user-only failure evidence與安全error。
- Concurrent append：讀取order deterministic；strict turn order/duplicate retry列為未決policy。
- History超限：只取最近N；另以測試記錄目前尚無total char/token cap的風險。
- Prompt injection in history：保持在untrusted delimiter。
- Citation in history：不擴大本次allowlist。
- Data access：repository test驗證conversation isolation；正式authorization另待SSO policy。
