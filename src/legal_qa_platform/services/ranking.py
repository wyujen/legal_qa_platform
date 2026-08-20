"""One deterministic implementation of vector/keyword candidate-union ranking."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from legal_qa_platform.domain.legal import (
    LegalProvision,
    provision_content_hash,
    provision_embedding_input_hash,
    provision_record_hash,
)
from legal_qa_platform.domain.profiles import RagProfile
from legal_qa_platform.domain.retrieval import RetrievalCandidate, RetrievalResult
from legal_qa_platform.services.normalization import (
    keyword_score,
    provision_search_text,
)


class MissingVectorScoreError(ValueError):
    """A candidate union was not fully rescored by the vector store."""


def _top_candidate_scores(
    candidates: Sequence[RetrievalCandidate],
    limit: int,
) -> dict[int, float]:
    """Deduplicate a source by its best score, then enforce ``candidate_k``."""

    best: dict[int, float] = {}
    for candidate in candidates:
        previous = best.get(candidate.provision_id)
        if previous is None or candidate.score > previous:
            best[candidate.provision_id] = candidate.score
    ordered = sorted(best.items(), key=lambda item: (-item[1], item[0]))
    return dict(ordered[:limit])


def _provision_map(
    provisions: Mapping[int, LegalProvision] | Sequence[LegalProvision],
) -> dict[int, LegalProvision]:
    if isinstance(provisions, Mapping):
        mapped = dict(provisions)
        for key, provision in mapped.items():
            if key != provision.provision_id:
                raise ValueError("provisions mapping key 必須等於 provision_id。")
        return mapped

    sequence_map: dict[int, LegalProvision] = {}
    for provision in provisions:
        if provision.provision_id in sequence_map:
            raise ValueError(f"provision_id 重複：{provision.provision_id}。")
        sequence_map[provision.provision_id] = provision
    return sequence_map


def hybrid_score(
    vector_score: float,
    lexical_score: float,
    profile: RagProfile,
) -> float:
    """Apply the explicit ``vector_weight * v + keyword_weight * k`` contract."""

    return profile.vector_weight * float(vector_score) + profile.keyword_weight * float(
        lexical_score
    )


def rank_candidate_union(
    question: str,
    *,
    provisions: Mapping[int, LegalProvision] | Sequence[LegalProvision],
    vector_candidates: Sequence[RetrievalCandidate] = (),
    keyword_candidates: Sequence[RetrievalCandidate] = (),
    union_vector_scores: Mapping[int, float] | None = None,
    trusted_record_hashes: Mapping[int, str] | None = None,
    profile: RagProfile | None = None,
    require_vector_scores: bool = True,
) -> list[RetrievalResult]:
    """Union both candidate sources, enrich locally, and return the profile Top K.

    Candidate-source scores decide membership in each source's ``candidate_k``.
    The caller must use the vector store's ``scores_for_ids`` equivalent and
    pass ``union_vector_scores`` for keyword-only IDs; this preserves the legacy
    behavior where every union member receives both components.  Missing scores
    fail by default.  Zero is used only when the caller explicitly chooses
    ``require_vector_scores=False`` for a degraded path or focused unit test.
    Lexical scores are always recomputed from trusted local master data.  A
    repository may pass its persisted ``trusted_record_hashes`` so QA retrieval
    snapshots refer to the exact published record; otherwise the same canonical
    hash is calculated locally.  Unknown or inactive IDs are safely omitted.
    """

    if not isinstance(question, str):
        raise TypeError("question 必須是字串。")
    if not question.strip():
        return []
    selected_profile = profile or RagProfile()
    local = _provision_map(provisions)
    vector_by_id = _top_candidate_scores(
        vector_candidates,
        selected_profile.candidate_k,
    )
    keyword_by_id = _top_candidate_scores(
        keyword_candidates,
        selected_profile.candidate_k,
    )
    candidate_ids = set(vector_by_id) | set(keyword_by_id)
    complete_vector_scores = dict(vector_by_id)
    if union_vector_scores is not None:
        for provision_id, raw_score in union_vector_scores.items():
            if isinstance(provision_id, bool) or not isinstance(provision_id, int):
                raise TypeError("union_vector_scores key 必須是 provision_id 整數。")
            if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
                raise TypeError("union_vector_scores value 必須是有限數值。")
            score = float(raw_score)
            if not math.isfinite(score):
                raise ValueError("union_vector_scores 不可含 NaN 或 Infinity。")
            complete_vector_scores[provision_id] = score

    scored: list[tuple[LegalProvision, float, float, float]] = []
    for provision_id in candidate_ids:
        provision = local.get(provision_id)
        if provision is None or not provision.is_active:
            continue
        if provision_id not in complete_vector_scores and require_vector_scores:
            raise MissingVectorScoreError(
                f"候選 union 尚未取得完整 vector score：provision_id={provision_id}。"
            )
        vector_value = float(complete_vector_scores.get(provision_id, 0.0))
        lexical_value = keyword_score(question, provision_search_text(provision))
        final_value = hybrid_score(vector_value, lexical_value, selected_profile)
        if final_value < selected_profile.min_score:
            continue
        scored.append((provision, vector_value, lexical_value, final_value))

    scored.sort(key=lambda item: (-item[3], item[0].provision_id))
    results: list[RetrievalResult] = []
    for rank, (provision, vector_value, lexical_value, final_value) in enumerate(
        scored[: selected_profile.top_k],
        start=1,
    ):
        results.append(
            RetrievalResult(
                provision_id=provision.provision_id,
                document_name=provision.document_name,
                article_no=provision.article_no,
                title=provision.title,
                content=provision.content,
                source_url=provision.source_url,
                content_hash=provision_content_hash(provision),
                record_hash=(
                    trusted_record_hashes[provision.provision_id]
                    if trusted_record_hashes is not None
                    and provision.provision_id in trusted_record_hashes
                    else provision_record_hash(provision)
                ),
                embedding_input_hash=provision_embedding_input_hash(provision),
                vector_score=vector_value,
                keyword_score=lexical_value,
                final_score=final_value,
                rank=rank,
            )
        )
    return results


# A concise alias for orchestration code.
rank_candidates = rank_candidate_union


__all__ = [
    "MissingVectorScoreError",
    "hybrid_score",
    "rank_candidate_union",
    "rank_candidates",
]
