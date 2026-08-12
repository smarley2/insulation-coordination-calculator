"""Generic clause-fragment extraction and normalization.

Raw fragments and token geometry stay private to the draft; recipes declare only
page/bbox/shape contracts. Extraction fails closed: any structural surprise raises
``ExtractionError`` instead of guessing.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Literal, NamedTuple

import pdfplumber
from pydantic import Field, model_validator

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import (
    Identifier,
    SourceReference,
)
from insulation_coordination.rules.importer.extract import (
    ExtractionError,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.identify import (
    ClauseAuditSpec,
    StandardIdentity,
)

ClauseTokenKind = Literal["reference", "quantity", "unit", "operator", "condition"]

_COMPARISON_TOKENS = {
    "<": "lt",
    ">": "gt",
    "<=": "lte",
    ">=": "gte",
    "≤": "lte",
    "≥": "gte",
}
_COMPARISON_WORDS = {
    "not exceeding": "lte",
    "exceeding": "gt",
    "below": "lt",
    "above": "gt",
    "up to": "lte",
}
_UNIT_TOKENS = {"s", "ms", "min", "h", "V", "kV", "A", "Hz", "kHz", "MHz", "m", "mm"}
_NUMBER = re.compile(r"^[0-9]+(?:[.,][0-9]+)?$")


class ClauseNode(FrozenModel):
    order: int = Field(ge=0)
    kind: Literal["paragraph", "bullet", "alternative"]
    raw_text: str = Field(max_length=4_000)
    source: SourceReference


class ClauseToken(FrozenModel):
    kind: ClauseTokenKind
    raw_text: str = Field(max_length=200)
    normalized: str | Decimal
    source: SourceReference


class RawClauseFragment(FrozenModel):
    id: Identifier
    raw_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    nodes: tuple[ClauseNode, ...] = Field(min_length=1)
    tokens: tuple[ClauseToken, ...]
    source: SourceReference

    @model_validator(mode="after")
    def _ordered_nodes(self) -> RawClauseFragment:
        if tuple(node.order for node in self.nodes) != tuple(range(len(self.nodes))):
            raise ValueError("clause nodes must be ordered from zero without gaps")
        return self


class _Line(NamedTuple):
    top: float
    text: str


def _lines(page: pdfplumber.page.Page, bbox: tuple[float, float, float, float]) -> list[_Line]:
    words = page.crop(bbox).extract_words(use_text_flow=False, keep_blank_chars=False)
    grouped: dict[float, list[tuple[float, str]]] = {}
    for word in words:
        top = float(word["top"])
        key = next((key for key in grouped if abs(key - top) <= 3.0), top)
        grouped.setdefault(key, []).append((float(word["x0"]), str(word["text"])))
    return [
        _Line(top, " ".join(text for _, text in sorted(parts)))
        for top, parts in sorted(grouped.items())
    ]


def _is_bullet(text: str) -> bool:
    return bool(re.match(r"^(\u2022|\u25aa|-|\*|[a-z]\)|[0-9]+\))\s", text)) or text.startswith(
        "SYMBOL "
    )


def _strip_bullet(text: str) -> str:
    return re.sub(r"^(\u2022|\u25aa|-|\*|[a-z]\)|[0-9]+\)|SYMBOL)\s+", "", text).strip()


def _classify_token(
    word: str,
    *,
    previous: str | None,
    source: SourceReference,
) -> ClauseToken | None:
    if word in _COMPARISON_TOKENS:
        return ClauseToken(
            kind="operator", raw_text=word, normalized=_COMPARISON_TOKENS[word], source=source
        )
    if _NUMBER.match(word):
        try:
            value = Decimal(word.replace(",", "."))
        except InvalidOperation:
            return None
        return ClauseToken(kind="quantity", raw_text=word, normalized=value, source=source)
    if word in _UNIT_TOKENS and previous is not None and _NUMBER.match(previous):
        return ClauseToken(kind="unit", raw_text=word, normalized=word, source=source)
    if re.fullmatch(r"[A-Za-z][A-Za-z-]+", word):
        return ClauseToken(kind="condition", raw_text=word, normalized=word, source=source)
    return None


def _tokens_for_node(
    node: ClauseNode,
    source: SourceReference,
) -> tuple[ClauseToken, ...]:
    tokens: list[ClauseToken] = []
    for match in re.finditer(r"\bfigure\s+([0-9]+)\b", node.raw_text, flags=re.IGNORECASE):
        tokens.append(
            ClauseToken(
                kind="reference",
                raw_text=match.group(0),
                normalized=f"figure-{match.group(1)}",
                source=source,
            )
        )
    lowered = node.raw_text.casefold()
    for phrase, code in _COMPARISON_WORDS.items():
        if phrase in lowered:
            tokens.append(
                ClauseToken(
                    kind="operator",
                    raw_text=phrase,
                    normalized=code,
                    source=source,
                )
            )
            break
    previous: str | None = None
    for word in node.raw_text.split():
        token = _classify_token(word, previous=previous, source=source)
        if token is not None:
            tokens.append(token)
        previous = word
    return tuple(tokens)


def extract_clause_fragment(
    page: pdfplumber.page.Page,
    spec: ClauseAuditSpec,
    identity: StandardIdentity,
) -> RawClauseFragment:
    """Extract one recipe-declared clause fragment, failing closed on surprises."""

    base = SourceReference(
        document_id=identity.recipe_id,
        standard=identity.standard,
        edition=identity.edition,
        page=spec.page_number,
        clause=spec.clause,
    )
    lines = _lines(page, spec.expected_bbox)
    if not lines:
        raise ExtractionError(f"clause structure mismatch for {spec.semantic_id}: bbox is empty")
    bullets = [line for line in lines if _is_bullet(line.text)]
    if spec.expected_root_kind == "bullets":
        if len(bullets) < 2:
            raise ExtractionError(
                f"clause structure mismatch for {spec.semantic_id}: expected bullet list"
            )
    elif bullets:
        raise ExtractionError(
            f"clause structure mismatch for {spec.semantic_id}: expected a paragraph"
        )

    nodes: list[ClauseNode] = []
    if spec.expected_root_kind == "paragraph":
        nodes.append(
            ClauseNode(
                order=0,
                kind="paragraph",
                raw_text=" ".join(line.text.strip() for line in lines),
                source=base.model_copy(
                    update={"row": f"paragraph starting at line top {lines[0].top:.1f}"}
                ),
            )
        )
    else:
        seen_bullet = False
        for line in lines:
            if _is_bullet(line.text):
                seen_bullet = True
                nodes.append(
                    ClauseNode(
                        order=len(nodes),
                        kind="bullet",
                        raw_text=_strip_bullet(line.text),
                        source=base.model_copy(update={"row": f"line top {line.top:.1f}"}),
                    )
                )
            elif seen_bullet and nodes:
                merged = f"{nodes[-1].raw_text} {line.text.strip()}"
                nodes[-1] = nodes[-1].model_copy(update={"raw_text": merged})
    nodes = [node.model_copy(update={"order": order}) for order, node in enumerate(nodes)]
    tokens = tuple(token for node in nodes for token in _tokens_for_node(node, node.source))
    fragment = RawClauseFragment(
        id=f"raw-{spec.semantic_id}",
        raw_sha256="0" * 64,
        nodes=tuple(nodes),
        tokens=tokens,
        source=base,
    )
    return fragment.model_copy(update={"raw_sha256": canonical_model_sha256(fragment)})


def normalize_clause_fragment(fragment: RawClauseFragment) -> RawClauseFragment:
    """Merge wrapped continuation lines deterministically; preserve hash and tokens."""

    merged: list[ClauseNode] = []
    for node in fragment.nodes:
        text = re.sub(r"\s+", " ", node.raw_text).strip()
        merged.append(node.model_copy(update={"raw_text": text, "order": len(merged)}))
    normalized = fragment.model_copy(update={"nodes": tuple(merged)})
    if normalized.raw_sha256 != fragment.raw_sha256:
        raise ExtractionError("clause normalization must preserve the raw hash")
    return normalized


__all__ = [
    "ClauseNode",
    "ClauseToken",
    "RawClauseFragment",
    "extract_clause_fragment",
    "normalize_clause_fragment",
]
