"""Generic clause-fragment extraction and normalization.

Raw fragments and token geometry stay private to the draft; recipes declare only
page/bbox/shape contracts. Extraction fails closed: any structural surprise raises
``ExtractionError`` instead of guessing.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from itertools import takewhile
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
    ClauseSegmentSpec,
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
    #: Which of the clause's declared segments this node was read from. Provenance, never
    #: application semantics: a node keeps the page and region it came from so a fact citing
    #: it says which physical part of the clause it rests on.
    segment_index: int = Field(default=0, ge=0)
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
    #: The ordered physical regions this fragment was read from, so the fragment's own hash
    #: covers the segment inventory as well as the extracted nodes: a clause re-declared over
    #: a different region re-opens its facts even where the text it reached is unchanged.
    #: Empty only for a fragment nothing extracted -- a synthetic one built in a test.
    segments: tuple[ClauseSegmentSpec, ...] = ()
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


def _segment_nodes(
    page: pdfplumber.page.Page,
    semantic_id: str,
    segment: ClauseSegmentSpec,
    segment_index: int,
    base: SourceReference,
) -> list[ClauseNode]:
    """Every node of one declared region, failing closed on a shape surprise.

    Checked per region rather than per clause: a clause whose parts are a bullet list and
    then running prose would pass no single root-shape check, and relaxing the check into
    "any kind" is what would let a reflowed clause project silently.

    A ``bullets`` region may open with its list's lead-in prose, which becomes a paragraph node
    before the bullets; a region's declared root kind is what its *list* reads as, not a promise
    that it contains nothing else.
    """

    lines = _lines(page, segment.expected_bbox)
    if not lines:
        raise ExtractionError(
            f"clause structure mismatch for {semantic_id}: segment {segment_index} bbox is empty"
        )
    bullets = [line for line in lines if _is_bullet(line.text)]
    if segment.expected_root_kind == "bullets":
        if len(bullets) < 2:
            raise ExtractionError(
                f"clause structure mismatch for {semantic_id}: segment {segment_index} "
                "expected bullet list"
            )
    elif bullets:
        raise ExtractionError(
            f"clause structure mismatch for {semantic_id}: segment {segment_index} "
            "expected a paragraph"
        )

    nodes: list[ClauseNode] = []
    if segment.expected_root_kind == "paragraph":
        nodes.append(
            ClauseNode(
                order=0,
                kind="paragraph",
                raw_text=" ".join(line.text.strip() for line in lines),
                segment_index=segment_index,
                source=base.model_copy(
                    update={"row": f"paragraph starting at line top {lines[0].top:.1f}"}
                ),
            )
        )
        return nodes
    # Lines before the first bullet are the list's own lead-in, and they are the sentence the
    # bullets complete: a bullet has no finite verb of its own. They used to be dropped on the
    # floor -- the shape check passed while the text that gave the bullets their modality was
    # never extracted, so a reviewer had to consult wording the fragment did not show. They
    # become one paragraph node preceding the bullets.
    lead_in = list(takewhile(lambda line: not _is_bullet(line.text), lines))
    if lead_in:
        nodes.append(
            ClauseNode(
                order=0,
                kind="paragraph",
                raw_text=" ".join(line.text.strip() for line in lead_in),
                segment_index=segment_index,
                source=base.model_copy(
                    update={"row": f"paragraph starting at line top {lead_in[0].top:.1f}"}
                ),
            )
        )
    for line in lines[len(lead_in) :]:
        if _is_bullet(line.text):
            nodes.append(
                ClauseNode(
                    order=len(nodes),
                    kind="bullet",
                    raw_text=_strip_bullet(line.text),
                    segment_index=segment_index,
                    source=base.model_copy(update={"row": f"line top {line.top:.1f}"}),
                )
            )
        else:
            merged = f"{nodes[-1].raw_text} {line.text.strip()}"
            nodes[-1] = nodes[-1].model_copy(update={"raw_text": merged})
    return nodes


def extract_clause_fragment(
    pdf: pdfplumber.pdf.PDF,
    spec: ClauseAuditSpec,
    identity: StandardIdentity,
) -> RawClauseFragment:
    """Extract one recipe-declared clause fragment, failing closed on surprises.

    One fragment per semantic clause however many physical regions it occupies: the declared
    segments are read in declared order, their nodes concatenated in that order, and every
    node keeps the page and segment it came from rather than inheriting the clause's first.
    """

    fragment_source = SourceReference(
        document_id=identity.recipe_id,
        standard=identity.standard,
        edition=identity.edition,
        page=spec.segments[0].page_number,
        clause=spec.clause,
    )
    nodes: list[ClauseNode] = []
    for segment_index, segment in enumerate(spec.segments):
        nodes.extend(
            _segment_nodes(
                pdf.pages[segment.page_number - 1],
                spec.semantic_id,
                segment,
                segment_index,
                fragment_source.model_copy(update={"page": segment.page_number}),
            )
        )
    nodes = [node.model_copy(update={"order": order}) for order, node in enumerate(nodes)]
    tokens = tuple(token for node in nodes for token in _tokens_for_node(node, node.source))
    fragment = RawClauseFragment(
        id=f"raw-{spec.semantic_id}",
        raw_sha256="0" * 64,
        nodes=tuple(nodes),
        tokens=tokens,
        segments=spec.segments,
        source=fragment_source,
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
