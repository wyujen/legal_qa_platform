# REST API

FastAPI 是 delivery adapter，entry point 為 `legal_qa_platform.api.app:app`。HTTP/Pydantic request mapping、status code與dependency wiring留在API layer；normalize、retrieval、ranking、prompt與validation只存在於application core。選擇與替換邊界見 [ADR-0001](adr/0001-fastapi-rest-boundary.md)。

## Run

```powershell
python -m legal_qa_platform.api.server --host 0.0.0.0 --port 8000
```

這個application-owned launcher在Windows使用psycopg async相容的selector event
loop；Linux及其他平台維持標準`asyncio.run`行為。Operator不應以直接呼叫
`uvicorn legal_qa_platform.api.app:app`取代它。

服務啟動前由Human Operator把文件化runtime variables注入目前process。Application不讀設定檔或搜尋credential。Local Swagger/OpenAPI由FastAPI產生；production是否公開documentation route屬deployment policy。

## Endpoints

| Method/path | Purpose | Critical dependencies |
|---|---|---|
| `GET /health` | Process liveness；不做遠端深度檢查 | none |
| `GET /ready` | 可安全接收QA traffic的shallow/deep contract checks | PostgreSQL schema/published snapshot, Qdrant service/collection, LiteLLM |
| `POST /api/v1/chat` | 完整conversation-aware RAG與已驗證answer | PostgreSQL, Qdrant, LiteLLM |
| `POST /api/v1/retrieve` | 共用retrieval pipeline的ranked results，不產生answer | PostgreSQL, Qdrant, LiteLLM embedding |
| `POST /api/v1/feedback` | 保存對既有query的feedback | PostgreSQL |

Langfuse永遠不是readiness或QA hard dependency。Experiment/batch/evaluation endpoints若日後加入，應與正式chat contract分開並受deployment access policy限制。

## Chat contract

Request：

```json
{
  "conversation_id": null,
  "message": "學生應在什麼期限內提出申請？",
  "profile": "platform-baseline-v1"
}
```

`message` 是1–4,000字的non-empty string；unknown fields被拒絕。`conversation_id` optional，且本身不是authorization proof。Baseline只允許已載入、通過validation的profile；client不能逐欄覆寫model/weights/collection來繞過可重現設定。

Response envelope：

```json
{
  "query_id": "<QUERY_ID>",
  "conversation_id": "<CONVERSATION_ID_OR_NULL>",
  "question": "<ORIGINAL_QUESTION>",
  "normalized_question": "<NORMALIZED_QUESTION>",
  "profile": "platform-baseline-v1",
  "response": {
    "can_answer": true,
    "summary": "<SANITIZED_ANSWER>",
    "conditions": [],
    "exceptions": [],
    "missing_information": [],
    "citations": [
      {
        "provision_id": 812,
        "document_name": "<LOCAL_DOCUMENT_NAME>",
        "article_no": "<LOCAL_ARTICLE_NO>"
      }
    ],
    "notice": "本回答僅供內部初步法規解析，不構成正式法律意見。"
  },
  "retrieval_results": [],
  "duration_ms": 321,
  "error": null
}
```

`response`只可能是validator產生的`LegalQaResponse`；model raw text不會出現在此欄位。Retrieval result可包含`provision_id`、local document/article/title/content snapshot、source/hash、vector/keyword/final score與rank，供內部MVP理解；正式學生API是否精簡debug fields需另訂versioned response policy。

## Retrieve contract

Retrieve endpoint接受問題與profile，走和chat相同的normalize、embedding、Qdrant/PostgreSQL candidate union、hybrid ranking、threshold與Top K。它不得另寫SQL/score formula。Response是deterministic ranked `RetrievalResult`清單，並保留各signal score/hash/rank以供evaluation與troubleshooting。

Expected answers、expected keywords與expected provision IDs只存在100題evaluation dataset，任何production request或response都不得帶它們進prompt。

## Feedback contract

Feedback關聯既有`query_id`，可帶受限rating/category/comment與optional conversation identity。API先做shape/length validation，再由repository確認query關係並寫PostgreSQL；不直接修改模型、法規資料或Langfuse dataset。正式feedback categories、moderation與retention仍是product/data-governance policy。

## Health semantics

`/health`應快速回200與固定service/status，不列settings/endpoints。`/ready`並行檢查
PostgreSQL application schema、符合目前profile的成功published snapshot、Qdrant service、
profile指定collection的Cosine/1024維contract，以及LiteLLM gateway；任一失敗時回
non-2xx。它不執行embedding或chat completion，指定model的實際operation仍由同步與
`python scripts/smoke_test.py`驗證。Response body只列上述dependency boolean/status，
不能包含URL、DSN、exception string、header或credential。

Kubernetes startup/liveness使用`/health`，readiness使用`/ready`。避免每個liveness call執行昂貴model completion。

## Errors

| Situation | Suggested HTTP class | Response rule |
|---|---|---|
| Request schema | 422 | field/category；不echo完整敏感內容 |
| Unknown profile | 404 | 固定safe detail；不回傳profile內容或settings |
| Unknown conversation/query | 404/typed 4xx | opaque identity only |
| No supporting provision | 200 typed `can_answer=false` | 不是infrastructure failure |
| PostgreSQL/Qdrant/LiteLLM unavailable | 503 | service + safe category/retryability |
| Model/structured validation failure | 502/controlled chat result | 不附raw model payload |
| Unexpected application bug | 500 | 固定safe error；server log亦redacted |

API不得回傳stack trace、request headers、settings dump或credential-bearing adapter exception。Error mapping應集中於API boundary，domain errors不引用FastAPI classes。
若日後加入correlation ID，必須使用application產生的opaque identifier並先納入
response/log contract；baseline不宣稱已提供此欄位。

## Streamlit client

`src/legal_qa_platform/ui/streamlit_app.py`只使用HTTP endpoints，不import QA service或database adapter。API base URL由non-secret CLI argument傳入：

```powershell
streamlit run src/legal_qa_platform/ui/streamlit_app.py -- --api-base-url http://localhost:8000
```

Compose/Kubernetes可把該argument改成service DNS；這不新增environment variable。UI應設定client timeout、顯示safe API error、以plain text render answer，且不顯示/記錄request headers。

## Versioning與未決security policy

所有product endpoints放在`/api/v1`。Framework/OpenAPI metadata可變，但domain meaning與backward compatibility需以contract tests保護。Student SSO/authorization、public CORS、rate limit、quota、formal domain與API exposure尚未定案；baseline不虛構身份機制。部署期間應限制入口至核准網路，待Human Operator提供正式policy後再實作。

## Contract tests

- OpenAPI包含五個baseline endpoints與預期methods。
- Request extra/type/length/profile validation；domain model不含FastAPI type。
- Chat成功/no-result/adapter failure/validation failure的status與safe body。
- `/health`不碰外部服務；`/ready`檢查schema/published snapshot、Qdrant
  service/collection與LiteLLM，但忽略Langfuse failure。
- Streamlit smoke以fake HTTP server驗證未import QA core。
- Error/response recursive secret-safety與raw model output isolation。
