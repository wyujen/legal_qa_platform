"""Public domain contracts for :mod:`legal_qa_platform`."""

from legal_qa_platform.domain.legal import (
    LegalProvision,
    StableProvisionKey,
    build_embedding_text,
    canonical_json_hash,
    canonicalize_stable_key,
    provision_content_hash,
    provision_embedding_input_hash,
    provision_official_content_hash,
    provision_record_hash,
    provisions_fingerprint,
)
from legal_qa_platform.domain.profiles import RagProfile
from legal_qa_platform.domain.qa import (
    LEGAL_NOTICE,
    ChatRequest,
    ChatResponse,
    Citation,
    LegalQaResponse,
    LLMAnswer,
    LLMCitation,
    QuestionBankItem,
)
from legal_qa_platform.domain.retrieval import (
    ContextItem,
    RagContext,
    RetrievalCandidate,
    RetrievalResult,
)

__all__ = [
    "Citation",
    "ChatRequest",
    "ChatResponse",
    "ContextItem",
    "LEGAL_NOTICE",
    "LLMAnswer",
    "LLMCitation",
    "LegalProvision",
    "LegalQaResponse",
    "QuestionBankItem",
    "RagContext",
    "RagProfile",
    "RetrievalCandidate",
    "RetrievalResult",
    "StableProvisionKey",
    "build_embedding_text",
    "canonical_json_hash",
    "canonicalize_stable_key",
    "provision_content_hash",
    "provision_embedding_input_hash",
    "provision_official_content_hash",
    "provision_record_hash",
    "provisions_fingerprint",
]
