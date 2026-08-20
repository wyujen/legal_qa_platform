# `legal_qa_platform` documentation map

用一筆真實 QA request 由外往內閱讀，不必先逐檔案看 source：

1. [Architecture](architecture.md)：元件責任、port/adapter 與可替換邊界。
2. [End-to-end data flow](data_flow.md)：一題從 Streamlit/API 到 validated answer。
3. [API](api.md)：HTTP contract、health/readiness 與 Streamlit client。
4. [Database](database.md) 與 [Conversation](conversation.md)：application-owned state。
5. [Ingestion](ingestion.md)：JSON、stable identity、hash、PostgreSQL/Qdrant sync。
6. [Retrieval](retrieval.md)：vector + keyword candidates、hybrid score、Top K。
7. [Context and prompt](context_and_prompt.md)：excerpt budget、prompt-injection boundary。
8. [Model gateway](model_gateway.md)：LiteLLM `bge-m3` / `campus-qa` contract。
9. [Validation](validation.md)：structured output、sanitization、citation allowlist。
10. [Observability](observability.md)：fail-open trace與metadata allowlist。
11. [Testing](testing.md)、[load testing](load_testing.md) 與 [troubleshooting](troubleshooting.md)。
12. [Configuration](configuration.md)、[security/secrets](security_and_secrets.md) 與 [deployment](deployment.md)。

Reference migration的保留／重構／淘汰盤點見 [reference_migration.md](reference_migration.md)。Durable decisions與重新評估條件見 [ADR index](adr/README.md)。

每一層都用五個問題理解：它為何存在、input/output、實際code、可調設定、失敗時如何重現/觀察/測試。完成理解的實務驗收是能安全修改profile Top K/weights或prompt version、重跑同步/evaluation、追查同一 `provision_id` 在兩個stores與trace的關係，並從load result判斷瓶頸在application或model gateway。
