# Structured Output 與 Citation Validation

Model output永遠是不可信資料。只有通過JSON解析、Pydantic schema、文字sanitization、語意完整性與本次retrieval citation allowlist的typed result，才能回到API/UI；raw completion不得作為fallback顯示。

## Response contract

Model必須產生的 `LLMAnswer` 包含：

```text
can_answer: boolean
summary: non-empty string
conditions: string[]
exceptions: string[]
missing_information: string[]
citations: [{provision_id, document_name, article_no}]
```

Model citation實際只允許選擇 `provision_id`；document name/article number由本地資料補齊。通過validator後的 outward `LegalQaResponse` 才加入本地固定的 `notice`。

Application result另帶query/conversation identity、original/normalized question、retrieval results、stage latency與安全error分類（實際HTTP schema以 [api.md](api.md) 為準）。固定notice由本地程式覆寫，不信任模型自行產生的免責內容。

## Validation order

1. 接受string/bytes/mapping但不接受任意object；bytes必須是UTF-8。
2. String必須從`{`開始並以`}`結束；前言、Markdown/code fence或多餘尾文一律拒絕，不做寬鬆salvage。
3. 解析單一JSON object，再以Pydantic model驗證required fields/types與extra-field prohibition。
4. `summary` 必須在清理前後皆非空；lists套數量上限。
5. 對所有display strings移除script/style、HTML tags、重複entity與internal provision markers。
6. 建立本次retrieval results的`provision_id → local snapshot` allowlist。
7. 丟棄allowlist外citation與duplicate ID；document name/article number一律以本地值覆寫。
8. 若model `can_answer=true`但沒有任何valid citation，降級為`can_answer=false`與固定unsupported summary/missing information。
9. 以本地fixed notice建立最終typed result。

不得只依model回傳的法規名稱/條號做allowlist，也不得用fuzzy match補上一個「看起來像」的ID。

## Citation allowlist

Allowlist只來自本次Top K retrieval output。Citation最多和response list上限一致並保留model引用順序中的first valid occurrence。被citation引用的ID在PostgreSQL/Qdrant/trace/evaluation皆使用同一stable identity。

Validator確認的是「citation ID屬於本次context且metadata可信」，不等同證明每句自然語言都有entailment。Answer quality仍靠prompt、100題evaluation與人工review；未來若加citation entailment scorer，應是獨立、可測experiment。

## Sanitization

UI只渲染plain text。HTML entity會有限次decode後移除dangerous blocks/tags；殘留angle bracket轉為全形以保留比較語意而不形成HTML。`[ProvisionId=...]`或`provision_id: ...`等internal markers從user-visible text移除，真正citation只走structured field。

Sanitization不是general malware scanner，也不能替代frontend escaping。API應設定JSON content type，Streamlit使用text rendering API，不把model output傳給unsafe HTML renderer。

## Error handling

- Empty/non-UTF8/malformed JSON/schema mismatch → validation error category。
- 空summary → validation error，不回raw text。
- Unsupported citations → filter；若因此無支持結論則降級。
- Adapter/provider response body可能含敏感或不可信內容，exception/log不收錄原文。
- 第一次structured parsing失敗時，QA service最多追加一次只要求依同一context/schema重輸出的repair call；第二次仍失敗即回受控錯誤，不可無界retry或切換成未驗證answer。

## Tests

- 正常full response、extra fields、wrong types、missing required、empty summary。
- Markdown前言/code fence、malformed/多個JSON object、invalid UTF-8皆被拒絕。
- Citation allowlist、duplicate、偽造metadata、無citation卻can_answer。
- HTML/script/style、nested entities、internal ID markers與list truncation。
- Fixed notice不可被model覆寫。
- Conversation提到但本次未retrieve的ID仍被拒絕。
- Property/fuzz cases不應把parser exception或raw payload洩漏到response。
