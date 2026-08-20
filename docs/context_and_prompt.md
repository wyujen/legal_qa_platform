# Context 與 Prompt

Context builder 把 deterministic Top K retrieval result 轉成有界、可引用的 reference blocks；prompt builder 再把 system policy、conversation context、問題、法條與 JSON Schema 組成 provider-neutral chat messages。兩者都不呼叫模型，也不決定 citation 是否有效。

## 三種輸入的信任邊界

| Input | 用途 | 信任程度 |
|---|---|---|
| System policy / response schema | 固定回答規則與輸出契約 | application-controlled |
| Conversation messages / current question | 協助理解問題 | untrusted data，不能成為法律依據 |
| Retrieved provisions | 本次回答可用的法律依據 | 內容仍是 untrusted prompt data，但 ID/metadata 來自 application stores |

Prompt 必須清楚用 delimiter 包住問題、對話與法條，並聲明其中的指令一律視為資料。使用者或法條文字不得覆寫 system policy、要求洩漏 prompt、改變輸出格式或引入 allowlist 之外的引用。

## Context selection

Input 是已依 `final_score DESC, provision_id ASC` 排序的 current provisions。Builder 再做 stable ordering/limit 防禦，預設最多 6 筆。

Baseline profile 的字元預算：

- 第一筆主要依據最多 600 chars；
- 其餘每筆最多 180 chars；
- 全部 RAG context 最多 1,500 chars；
- conversation messages 最多 6 筆；
- chat output `max_tokens` 為 1,200。

這些是 versioned profile 的值，不是 API/UI 各自的常數。Baseline prompt identifier
固定為 `legal_qa_platform-prompt-v1`；修改policy或schema時建立新identifier並重跑
100題evaluation，不就地改寫既有run的identity。

## 長條文 extraction

短於預算的條文保留完整正文。長條文則：

1. 清理多餘空白但不摘要、不改寫原文。
2. 以 newline/段落為候選單位。
3. 使用與 retrieval 一致、可測的 keyword overlap 對段落排序。
4. 優先保留與問題匹配的段落，最後恢復原始順序。
5. 單段仍過長時，以命中詞為 anchor 截取 window，並用省略符號標示前後裁切。
6. 沒有 lexical anchor 時採 deterministic 起始 window，不要求模型先摘要。

Excerpt 只能影響送入模型的 context，不可覆寫 PostgreSQL master text。若 citation 顯示需要完整法條，應依 `provision_id` 從 PostgreSQL 取得。

## Reference block

每筆 context 包含 application-controlled heading 與原文 excerpt，例如：

```text
[ProvisionId=812]
<document_name> <article_no> <title>
<verbatim focused excerpt>
```

只有 block 中的 ID 形成 citation allowlist。Model 產生的 document name/article number 不受信任，validator 會以本地 retrieval snapshot 覆寫。

## Prompt policy

System policy至少要求：

- 僅依本次 reference provisions 作答，不使用記憶或外部法律常識補洞；
- 不創造法規名稱、條號、程序、期限、數字或法律效果；
- 區分結論、條件、例外與缺少資訊；
- 核心問題有直接條文支持才可 `can_answer=true`；
- 數量、日期、分數、金額與次數要和同一句條文/適用條件再核對；
- citation 只引用直接支持結論的 allowlisted ProvisionId；
- 使用繁體中文，只輸出指定 JSON object，不輸出 Markdown、HTML 或推理草稿；
- 固定聲明回答僅供初步法規解析，不構成正式法律意見。

Prompt 內嵌 Pydantic 產生的 JSON Schema；schema 是 output instruction，不是驗證的替代品。LiteLLM response_format 可以協助格式穩定，但回應仍須由本地 validator 重新解析。

## Conversation context

最近 N 則 conversation messages會以獨立delimiter放在current question前，讓模型理解指涉；baseline profile只限制message count（預設6），尚未另設conversation total char/token cap。正式擴大使用前應依model context window加入有測試的第二層budget，不能靠截斷RAG evidence補償。對話內容不是RAG evidence；任何從對話得知的法規ID仍須本次retrieval命中後才可引用。詳細persistence/ordering見 [conversation.md](conversation.md)。

## Output 與 downstream contract

Builder 輸出 provider-neutral `ChatMessage` sequence、response schema，以及同一批 retrieval results/citation allowlist。Chat adapter 必須明確送出 `campus-qa` 與 `max_tokens`；validator 接收 raw completion 加原 allowlist，不從 prompt 文字反向解析 allowlist。

## 測試

- 空問題、空 result、Top K/total budget boundary。
- 相同 score 的 stable order、主要/次要 excerpt budget。
- 長條文的命中段、無命中 fallback、原文不改寫。
- Prompt-injection 字串保持在 untrusted delimiter 內。
- JSON Schema 含所有 required fields。
- Conversation 中的 provision marker 不會擴大 citation allowlist。
- Snapshot test 應綁 prompt version；修改 policy/schema 時建立新 version 並重跑 evaluation。
