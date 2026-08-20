from __future__ import annotations

import pytest
from pydantic import ValidationError

from legal_qa_platform.domain.profiles import RagProfile
from legal_qa_platform.domain.qa import LLMAnswer, QuestionBankItem


def question_payload() -> dict[str, object]:
    return {
        "question_id": "Q001",
        "question": "申請期限為何？",
        "expected_answer": "應於七日內申請。",
        "expected_keywords": ["七日", "申請"],
        "expected_provision_ids": [9],
        "document_name": "測試法規",
        "article_no": "第一條",
    }


def test_question_bank_item_is_strict_and_rejects_normalized_duplicates() -> None:
    assert QuestionBankItem.model_validate(question_payload()).question_id == "Q001"

    duplicate = question_payload()
    duplicate["expected_keywords"] = ["ＡＢＣ", "abc"]
    with pytest.raises(ValidationError, match="重複"):
        QuestionBankItem.model_validate(duplicate)

    wrong_id = question_payload()
    wrong_id["expected_provision_ids"] = ["9"]
    with pytest.raises(ValidationError):
        QuestionBankItem.model_validate(wrong_id)


def test_llm_schema_allows_only_localizable_citation_ids_and_has_no_notice() -> None:
    schema = LLMAnswer.model_json_schema()

    assert "notice" not in schema["properties"]
    assert "notice" not in schema["required"]
    citation_schema = schema["$defs"]["LLMCitation"]
    assert set(citation_schema["properties"]) == {"provision_id"}
    assert citation_schema["additionalProperties"] is False

    with pytest.raises(ValidationError):
        LLMAnswer.model_validate(
            {
                "can_answer": True,
                "summary": "可以申請。",
                "conditions": [],
                "exceptions": [],
                "missing_information": [],
                "citations": [
                    {
                        "provision_id": 9,
                        "document_name": "模型不得提供此欄位",
                    }
                ],
            }
        )


def test_baseline_profile_contains_all_runtime_experiment_contract_defaults() -> None:
    profile = RagProfile()

    assert profile.model_dump() == {
        "name": "platform-baseline-v1",
        "chat_model": "campus-qa",
        "embedding_model": "bge-m3",
        "embedding_dimension": 1024,
        "vector_collection": "legal_provisions_bge_m3_v1",
        "candidate_k": 50,
        "top_k": 6,
        "min_score": 0.12,
        "vector_weight": 0.65,
        "keyword_weight": 0.35,
        "reranker_enabled": False,
        "prompt_name": "legal_qa_platform-prompt-v1",
        "primary_context_chars": 600,
        "secondary_context_chars": 180,
        "max_context_chars": 1500,
        "conversation_message_limit": 6,
        "chat_max_tokens": 1200,
    }


@pytest.mark.parametrize(
    "updates",
    [
        {"candidate_k": 5, "top_k": 6},
        {"vector_weight": 0.6, "keyword_weight": 0.3},
        {"reranker_enabled": True},
        {"primary_context_chars": 601, "max_context_chars": 600},
        {"embedding_dimension": "1024"},
        {"unknown": "value"},
    ],
)
def test_profile_rejects_non_baseline_or_ambiguous_values(
    updates: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RagProfile.model_validate(updates)
