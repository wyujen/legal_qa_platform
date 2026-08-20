from __future__ import annotations

import pytest

from legal_qa_platform.domain.legal import LegalProvision
from legal_qa_platform.domain.profiles import RagProfile
from legal_qa_platform.domain.retrieval import RetrievalCandidate
from legal_qa_platform.services.context import build_context
from legal_qa_platform.services.normalization import (
    compact_keyword_text,
    extract_keyword_terms,
    keyword_score,
    normalize_text,
)
from legal_qa_platform.services.ranking import (
    MissingVectorScoreError,
    hybrid_score,
    rank_candidate_union,
)


def make_provision(
    provision_id: int,
    content: str,
    *,
    active: bool = True,
) -> LegalProvision:
    return LegalProvision(
        provision_id=provision_id,
        document_name="測試法規",
        article_no=f"第{provision_id}條",
        content=content,
        sort_order=provision_id,
        is_active=active,
    )


def test_legacy_normalization_punctuation_synonyms_and_keyword_contract() -> None:
    assert normalize_text("  ＡＢＣ　補資料逾期？ 老師說。 ") == (
        "abc 補件超過期限? 教師說."
    )
    assert compact_keyword_text("第 １２ 條之 ３？") == "第12條之3"

    terms = extract_keyword_terms("請問第 12 條，教師申請 ABC 期限如何？")
    assert "第12條" in terms
    assert "教師" in terms
    assert "abc" in terms
    assert "請問" not in terms
    assert keyword_score("教師申請", "依規定，教師申請應於七日內提出。") == 1.0


def test_candidate_union_uses_exact_point_65_point_35_formula_and_top_k() -> None:
    provisions = [
        make_provision(1, "教師申請"),
        make_provision(2, "教師申請"),
        make_provision(3, "完全不同內容"),
    ]
    profile = RagProfile(candidate_k=3, top_k=3, min_score=0.0)

    results = rank_candidate_union(
        "教師申請",
        provisions=provisions,
        vector_candidates=[
            RetrievalCandidate(provision_id=1, score=0.8),
            RetrievalCandidate(provision_id=3, score=0.9),
        ],
        keyword_candidates=[RetrievalCandidate(provision_id=2, score=1.0)],
        union_vector_scores={2: 0.2},
        profile=profile,
    )

    assert hybrid_score(0.8, 1.0, profile) == pytest.approx(0.87)
    assert [result.provision_id for result in results] == [1, 3, 2]
    assert results[0].vector_score == 0.8
    assert results[0].keyword_score == 1.0
    assert results[0].final_score == pytest.approx(0.87)
    assert results[2].vector_score == 0.2
    assert results[2].final_score == pytest.approx(0.48)
    assert [result.rank for result in results] == [1, 2, 3]
    assert all(len(result.content_hash) == 64 for result in results)
    assert all(len(result.record_hash) == 64 for result in results)
    assert all(len(result.embedding_input_hash) == 64 for result in results)


def test_keyword_only_union_member_requires_explicit_vector_rescore() -> None:
    with pytest.raises(MissingVectorScoreError, match="provision_id=1"):
        rank_candidate_union(
            "教師",
            provisions=[make_provision(1, "教師")],
            keyword_candidates=[RetrievalCandidate(provision_id=1, score=1.0)],
            profile=RagProfile(candidate_k=1, top_k=1, min_score=0.0),
        )

    degraded = rank_candidate_union(
        "教師",
        provisions=[make_provision(1, "教師")],
        keyword_candidates=[RetrievalCandidate(provision_id=1, score=1.0)],
        profile=RagProfile(candidate_k=1, top_k=1, min_score=0.0),
        require_vector_scores=False,
    )
    assert degraded[0].vector_score == 0.0


def test_candidate_union_omits_unknown_and_inactive_ids() -> None:
    results = rank_candidate_union(
        "教師",
        provisions=[make_provision(1, "教師", active=False)],
        vector_candidates=[
            RetrievalCandidate(provision_id=1, score=1.0),
            RetrievalCandidate(provision_id=999, score=1.0),
        ],
        profile=RagProfile(candidate_k=2, top_k=2, min_score=0.0),
    )

    assert results == []


def test_context_uses_profile_top_k_and_legacy_600_180_focus_limits() -> None:
    long_primary = (
        ("不相關沿革說明。" * 100)
        + "\n教師申請應於七日內提出完整文件。\n"
        + ("其他不相關規定。" * 100)
    )
    long_secondary = ("次要說明。" * 100) + "\n教師申請需附證明。"
    ranked = rank_candidate_union(
        "教師申請",
        provisions=[
            make_provision(1, long_primary),
            make_provision(2, long_secondary),
            make_provision(3, "教師申請第三順位"),
        ],
        vector_candidates=[
            RetrievalCandidate(provision_id=1, score=1.0),
            RetrievalCandidate(provision_id=2, score=0.9),
            RetrievalCandidate(provision_id=3, score=0.8),
        ],
        profile=RagProfile(candidate_k=3, top_k=3, min_score=0.0),
    )
    profile = RagProfile(candidate_k=3, top_k=2, min_score=0.0)

    context = build_context("教師申請", ranked, profile)

    assert [item.provision_id for item in context.items] == [1, 2]
    assert "教師申請應於七日內" in context.items[0].excerpt
    assert len(context.items[0].excerpt) <= 600
    assert len(context.items[1].excerpt) <= 180
    assert sum(len(item.excerpt) for item in context.items) + 1 <= 1500
    assert all(len(item.excerpt_hash) == 64 for item in context.items)
    assert context.items[0].record_hash == ranked[0].record_hash
