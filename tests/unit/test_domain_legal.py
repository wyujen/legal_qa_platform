from __future__ import annotations

import pytest
from pydantic import ValidationError

from legal_qa_platform.domain.legal import (
    LegalProvision,
    build_embedding_text,
    canonicalize_stable_key,
    provision_embedding_input_hash,
    provision_official_content_hash,
    provision_record_hash,
)


def make_provision(**updates: object) -> LegalProvision:
    payload: dict[str, object] = {
        "provision_id": 9,
        "document_name": "測試法規",
        "chapter_name": "第一章",
        "section_name": "",
        "article_no": "第一條",
        "paragraph_no": None,
        "subparagraph_no": None,
        "title": "申請",
        "content": "申請人應提出文件。",
        "search_text": "",
        "sort_order": 1,
        "source_url": "https://example.invalid/law",
        "is_active": True,
    }
    payload.update(updates)
    return LegalProvision.model_validate(payload)


def test_legal_provision_is_strict_and_populates_complete_search_text() -> None:
    provision = make_provision()

    assert provision.search_text == ("測試法規 第一章 第一條 申請 申請人應提出文件。")
    with pytest.raises(ValidationError):
        make_provision(provision_id="9")
    with pytest.raises(ValidationError):
        make_provision(is_active=1)
    with pytest.raises(ValidationError):
        make_provision(unexpected="value")


def test_stable_key_canonicalizes_unicode_and_whitespace_but_preserves_null() -> None:
    assert canonicalize_stable_key(
        " Ａ 法\n規 ",
        " 第 １ 條 ",
        None,
        None,
    ) == ("A 法 規", "第 1 條", None, None)

    with pytest.raises(TypeError, match="paragraph_no"):
        canonicalize_stable_key("法規", "第一條", "1", None)  # type: ignore[arg-type]


def test_official_record_and_embedding_hashes_have_distinct_semantics() -> None:
    original = make_provision()
    moved = make_provision(
        provision_id=99,
        sort_order=42,
        source_url="https://example.invalid/moved",
        is_active=False,
        search_text="額外檢索提示",
    )

    assert provision_official_content_hash(original) == (
        provision_official_content_hash(moved)
    )
    assert provision_record_hash(original) != provision_record_hash(moved)
    assert provision_embedding_input_hash(original) != (
        provision_embedding_input_hash(moved)
    )
    assert len(provision_record_hash(original)) == 64


def test_embedding_text_never_loses_official_body_when_search_hint_is_stale() -> None:
    provision = make_provision(search_text="只是一個額外提示")

    embedding_text = build_embedding_text(provision)

    assert "測試法規" in embedding_text
    assert "第一條" in embedding_text
    assert "申請人應提出文件。" in embedding_text
    assert embedding_text.endswith("只是一個額外提示")
