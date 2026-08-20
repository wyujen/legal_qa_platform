"""Internal MVP UI and question-bank browser over the REST API."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

import httpx
import streamlit as st


def _api_base_url() -> str:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--api-base-url",
        default="http://localhost:8000",
    )
    arguments, _ = parser.parse_known_args()
    return str(arguments.api_base_url).rstrip("/")


@st.cache_data  # type: ignore[untyped-decorator]
def _load_questions() -> list[dict[str, Any]]:
    path = Path.cwd() / "data" / "qa_test_questions.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    return (
        [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, list)
        else []
    )


def _post(base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        response = httpx.post(
            f"{base_url}{path}",
            json=payload,
            timeout=120.0,
            trust_env=False,
        )
        response.raise_for_status()
        data = response.json()
    except httpx.TimeoutException:
        raise RuntimeError("API request timed out.") from None
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"API returned HTTP {exc.response.status_code}.") from None
    except (httpx.RequestError, ValueError):
        raise RuntimeError("API is unavailable or returned invalid JSON.") from None
    if not isinstance(data, dict):
        raise RuntimeError("API response must be a JSON object.")
    return data


def main() -> None:
    st.set_page_config(page_title="legal_qa_platform", layout="wide")
    st.title("legal_qa_platform")
    st.caption("內部法規問答 MVP；回答僅供初步解析。")

    base_url = _api_base_url()
    questions = _load_questions()
    if "conversation_id" not in st.session_state:
        st.session_state.conversation_id = None
    if "question" not in st.session_state:
        st.session_state.question = ""

    with st.sidebar:
        st.subheader("100 題評估題庫")
        if questions and st.button("隨機選一題"):
            selected = random.choice(questions)  # noqa: S311 - UI-only sampling
            st.session_state.question = str(selected.get("question", ""))
            st.session_state.selected_evaluation = selected
        if st.button("開始新對話"):
            st.session_state.conversation_id = None
            st.session_state.pop("last_result", None)
        st.code(f"API: {base_url}", language=None)

    question = st.text_area(
        "問題",
        key="question",
        height=120,
        placeholder="請輸入要查詢的法規問題",
    )
    if st.button("送出", type="primary", disabled=not question.strip()):
        request_payload: dict[str, Any] = {
            "message": question,
            "profile": "platform-baseline-v1",
        }
        if st.session_state.conversation_id:
            request_payload["conversation_id"] = st.session_state.conversation_id
        try:
            with st.spinner("檢索條文並產生回答…"):
                result = _post(base_url, "/api/v1/chat", request_payload)
        except RuntimeError as exc:
            st.error(str(exc))
        else:
            st.session_state.last_result = result
            st.session_state.conversation_id = result.get("conversation_id")

    result = st.session_state.get("last_result")
    if isinstance(result, dict):
        response = result.get("response")
        if isinstance(response, dict):
            st.subheader("初步解析")
            st.text(str(response.get("summary", "")))
            for label, key in (
                ("適用條件", "conditions"),
                ("可能例外", "exceptions"),
                ("尚需確認", "missing_information"),
            ):
                values = response.get(key)
                if isinstance(values, list) and values:
                    st.markdown(f"#### {label}")
                    for value in values:
                        st.text(f"• {value}")
            citations = response.get("citations")
            if isinstance(citations, list) and citations:
                st.markdown("#### 引用")
                for citation in citations:
                    if isinstance(citation, dict):
                        st.text(
                            "• "
                            f"{citation.get('document_name', '')} "
                            f"{citation.get('article_no', '')}"
                        )
            st.caption(str(response.get("notice", "")))

        with st.expander("檢索除錯資訊"):
            st.json(result.get("retrieval_results", []))
            st.text(f"總耗時：{result.get('duration_ms', 0)} ms")
            st.text(f"Query ID：{result.get('query_id', '')}")

        query_id = result.get("query_id")
        if isinstance(query_id, str):
            left, right = st.columns(2)
            if left.button("👍 有幫助"):
                try:
                    _post(
                        base_url,
                        "/api/v1/feedback",
                        {
                            "query_id": query_id,
                            "conversation_id": st.session_state.conversation_id,
                            "rating": 1,
                        },
                    )
                    st.success("已記錄回饋。")
                except RuntimeError as exc:
                    st.error(str(exc))
            if right.button("👎 需改進"):
                try:
                    _post(
                        base_url,
                        "/api/v1/feedback",
                        {
                            "query_id": query_id,
                            "conversation_id": st.session_state.conversation_id,
                            "rating": -1,
                        },
                    )
                    st.success("已記錄回饋。")
                except RuntimeError as exc:
                    st.error(str(exc))

    selected = st.session_state.get("selected_evaluation")
    if isinstance(selected, dict):
        with st.expander("題庫 expected values（僅人工評估，不送入模型）"):
            st.text(str(selected.get("expected_answer", "")))
            st.json(
                {
                    "expected_keywords": selected.get("expected_keywords", []),
                    "expected_provision_ids": selected.get(
                        "expected_provision_ids", []
                    ),
                }
            )


if __name__ == "__main__":
    main()
