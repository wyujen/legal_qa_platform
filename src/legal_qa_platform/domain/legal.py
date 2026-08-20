"""Legal master-data models and deterministic identity/hash helpers.

This module is deliberately infrastructure-free.  A database row, a JSON seed
record, and an ingestion command all use the same stable-key and hashing rules.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
Sha256Hex = Annotated[
    str,
    StringConstraints(
        strict=True,
        to_lower=True,
        pattern=r"^[0-9a-f]{64}$",
    ),
]
StableProvisionKey: TypeAlias = tuple[str, str, int | None, int | None]

_WHITESPACE_RE = re.compile(r"\s+")


def canonicalize_identity_text(value: str) -> str:
    """Canonicalize a stable-key text component without changing semantics.

    Unicode width/compatibility variants and whitespace-only differences must
    not mint a new provision identity.  Punctuation and wording are retained:
    a renamed law is intentionally a new document.
    """

    if not isinstance(value, str):
        raise TypeError("stable key 的文字欄位必須是字串。")
    return _WHITESPACE_RE.sub(" ", unicodedata.normalize("NFKC", value)).strip()


def canonicalize_stable_key(
    document_name: str,
    article_no: str,
    paragraph_no: int | None,
    subparagraph_no: int | None,
) -> StableProvisionKey:
    """Return the canonical, non-lossy provision identity.

    ``None`` is significant and is never converted to zero or an empty string.
    Integer inputs are checked strictly so that a collector cannot silently turn
    an ambiguous string into a different identity.
    """

    if paragraph_no is not None and (
        isinstance(paragraph_no, bool) or not isinstance(paragraph_no, int)
    ):
        raise TypeError("paragraph_no 必須是整數或 None。")
    if subparagraph_no is not None and (
        isinstance(subparagraph_no, bool) or not isinstance(subparagraph_no, int)
    ):
        raise TypeError("subparagraph_no 必須是整數或 None。")

    canonical_document = canonicalize_identity_text(document_name)
    canonical_article = canonicalize_identity_text(article_no)
    if not canonical_document or not canonical_article:
        raise ValueError("stable key 的法規名稱與條號不得為空。")
    return (
        canonical_document,
        canonical_article,
        paragraph_no,
        subparagraph_no,
    )


def _canonical_json_value(payload: Any) -> Any:
    if isinstance(payload, BaseModel):
        return payload.model_dump(mode="json")
    if isinstance(payload, Mapping):
        return {
            str(key): _canonical_json_value(value) for key, value in payload.items()
        }
    if isinstance(payload, (list, tuple)):
        return [_canonical_json_value(value) for value in payload]
    return payload


def canonical_json(payload: Any) -> str:
    """Serialize JSON-compatible data in the one canonical form used for hashes."""

    return json.dumps(
        _canonical_json_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_text(value: str) -> str:
    """Hash the exact UTF-8 representation of ``value``."""

    if not isinstance(value, str):
        raise TypeError("SHA-256 輸入必須是字串。")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json_hash(payload: Any) -> str:
    """Hash a JSON-compatible payload after deterministic serialization."""

    return sha256_text(canonical_json(payload))


class LegalProvision(BaseModel):
    """One current legal provision, preserving the validated seed-data schema."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )

    provision_id: int = Field(strict=True, gt=0)
    document_name: NonEmptyText
    chapter_name: str = ""
    section_name: str = ""
    article_no: NonEmptyText
    paragraph_no: int | None = Field(default=None, strict=True, ge=1)
    subparagraph_no: int | None = Field(default=None, strict=True, ge=1)
    title: str = ""
    content: NonEmptyText
    search_text: str = ""
    sort_order: int = Field(strict=True, gt=0)
    source_url: str = ""
    is_active: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def populate_search_text(self) -> LegalProvision:
        """Always give retrieval a complete local fallback search document."""

        if not self.search_text:
            self.search_text = " ".join(
                part
                for part in (
                    self.document_name,
                    self.chapter_name,
                    self.section_name,
                    self.article_no,
                    self.title,
                    self.content,
                )
                if part
            )
        return self

    @property
    def stable_key(self) -> StableProvisionKey:
        return canonicalize_stable_key(
            self.document_name,
            self.article_no,
            self.paragraph_no,
            self.subparagraph_no,
        )


def build_embedding_text(provision: LegalProvision) -> str:
    """Build the complete embedding input from official text plus search hints.

    The official name, structural labels, article number, title, and full body
    are always present.  A collector-provided ``search_text`` is appended only
    when it adds information; it can never replace the official body.
    """

    canonical = " ".join(
        part
        for part in (
            provision.document_name,
            provision.chapter_name,
            provision.section_name,
            provision.article_no,
            provision.title,
            provision.content,
        )
        if part
    )
    canonical = " ".join(canonical.split())
    provided = " ".join(provision.search_text.split())
    if not provided or provided == canonical:
        return canonical
    return f"{canonical} {provided}"


def provision_official_content_hash(provision: LegalProvision) -> str:
    """Hash canonicalized official identity, structure, title, and full body.

    Runtime/collection metadata (ID, ordering, source URL, current flag, and
    search hints) is excluded, so moving an unchanged provision does not pretend
    its official text changed.
    """

    official_payload = {
        "document_name": canonicalize_identity_text(provision.document_name),
        "chapter_name": canonicalize_identity_text(provision.chapter_name),
        "section_name": canonicalize_identity_text(provision.section_name),
        "article_no": canonicalize_identity_text(provision.article_no),
        "paragraph_no": provision.paragraph_no,
        "subparagraph_no": provision.subparagraph_no,
        "title": canonicalize_identity_text(provision.title),
        "content": canonicalize_identity_text(provision.content),
    }
    return canonical_json_hash(official_payload)


def provision_record_hash(provision: LegalProvision) -> str:
    """Hash the complete canonical record, including collection metadata."""

    return canonical_json_hash(provision)


# ``content_hash`` in retrieval/vector payloads means official legal content.
provision_content_hash = provision_official_content_hash


def provision_embedding_input_hash(provision: LegalProvision) -> str:
    """Hash exactly the text sent to the embedding provider."""

    return sha256_text(build_embedding_text(provision))


def provisions_fingerprint(provisions: Sequence[LegalProvision]) -> str:
    """Hash an ordered snapshot, including its global ``sort_order`` contract."""

    return canonical_json_hash(list(provisions))


__all__ = [
    "LegalProvision",
    "NonEmptyText",
    "Sha256Hex",
    "StableProvisionKey",
    "build_embedding_text",
    "canonical_json",
    "canonical_json_hash",
    "canonicalize_identity_text",
    "canonicalize_stable_key",
    "provision_content_hash",
    "provision_embedding_input_hash",
    "provision_official_content_hash",
    "provision_record_hash",
    "provisions_fingerprint",
    "sha256_text",
]
