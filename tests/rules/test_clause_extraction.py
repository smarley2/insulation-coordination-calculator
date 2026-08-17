"""Synthetic clause-fragment extraction and normalization. No IEC content."""

from __future__ import annotations

from decimal import Decimal

import pdfplumber
import pytest

from insulation_coordination.rules.importer.clauses import (
    extract_clause_fragment,
    normalize_clause_fragment,
)
from insulation_coordination.rules.importer.extract import ExtractionError
from insulation_coordination.rules.importer.identify import (
    ClauseAuditSpec,
    ClauseSegmentSpec,
    StandardIdentity,
)
from tests.fixtures.synthetic_pdf import (
    create_clause_pdf,
    create_multi_segment_clause_pdf,
    create_paragraph_clause_pdf,
)

IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="4" * 64,
    page_count=3,
    recipe_id="synthetic-clause",
)
BBOX = (70.0, 300.0, 524.0, 700.0)
#: The multi-segment fixture's three regions, in reading order: page 2's foot, page 3's head,
#: then a paragraph region further down page 3.
FOOT_SEGMENT = ClauseSegmentSpec(
    page_number=2, expected_bbox=(70.0, 560.0, 540.0, 640.0), expected_root_kind="bullets"
)
HEAD_SEGMENT = ClauseSegmentSpec(
    page_number=3, expected_bbox=(70.0, 60.0, 540.0, 140.0), expected_root_kind="bullets"
)
PROSE_SEGMENT = ClauseSegmentSpec(
    page_number=3, expected_bbox=(70.0, 370.0, 540.0, 410.0), expected_root_kind="paragraph"
)


def synthetic_clause_spec() -> ClauseAuditSpec:
    return ClauseAuditSpec(
        semantic_id="synthetic.clause.applicability",
        clause="9.9.9",
        segments=(
            ClauseSegmentSpec(
                page_number=3,
                expected_bbox=BBOX,
                expected_root_kind="bullets",
            ),
        ),
        output_kind="decision",
    )


def _segmented_spec(*segments: ClauseSegmentSpec) -> ClauseAuditSpec:
    return synthetic_clause_spec().model_copy(update={"segments": segments})


def _with_root_kind(spec: ClauseAuditSpec, kind: str) -> ClauseAuditSpec:
    return spec.model_copy(
        update={
            "segments": tuple(
                segment.model_copy(update={"expected_root_kind": kind}) for segment in spec.segments
            )
        }
    )


def _with_bbox(spec: ClauseAuditSpec, bbox: tuple[float, float, float, float]) -> ClauseAuditSpec:
    return spec.model_copy(
        update={
            "segments": tuple(
                segment.model_copy(update={"expected_bbox": bbox}) for segment in spec.segments
            )
        }
    )


@pytest.fixture
def clause_pdf(tmp_path):
    path = tmp_path / "clause.pdf"
    create_clause_pdf(path)
    with pdfplumber.open(path) as pdf:
        yield pdf


@pytest.fixture
def segmented_pdf(tmp_path):
    path = tmp_path / "segments.pdf"
    create_multi_segment_clause_pdf(path)
    with pdfplumber.open(path) as pdf:
        yield pdf


def test_extracts_nodes_in_reading_order_with_page_provenance(clause_pdf) -> None:
    fragment = extract_clause_fragment(clause_pdf, synthetic_clause_spec(), IDENTITY)
    assert [node.order for node in fragment.nodes] == list(range(len(fragment.nodes)))
    assert all(token.source.page == 3 for token in fragment.tokens)
    assert fragment.id == "raw-synthetic.clause.applicability"
    assert all(node.kind == "bullet" for node in fragment.nodes)


def test_fragment_hash_is_stable(clause_pdf) -> None:
    first = extract_clause_fragment(clause_pdf, synthetic_clause_spec(), IDENTITY)
    second = extract_clause_fragment(clause_pdf, synthetic_clause_spec(), IDENTITY)
    assert first.raw_sha256 == second.raw_sha256
    assert len(first.raw_sha256) == 64


def test_normalization_preserves_hash_spans_and_merges_wrapped_lines(clause_pdf) -> None:
    fragment = extract_clause_fragment(clause_pdf, synthetic_clause_spec(), IDENTITY)
    normalized = normalize_clause_fragment(fragment)
    assert normalized.raw_sha256 == fragment.raw_sha256
    assert [node.order for node in normalized.nodes] == list(range(len(normalized.nodes)))
    # The second bullet wraps across two physical lines; normalization merges them.
    assert len(normalized.nodes) == 2
    assert "wrapped" in normalized.nodes[1].raw_text
    assert "continues" in normalized.nodes[1].raw_text
    assert normalized.tokens == fragment.tokens


def test_a_bullet_lists_lead_in_becomes_a_paragraph_node_before_the_bullets(clause_pdf) -> None:
    """A bullet completes its lead-in, so a region reaching one must extract it.

    Dropped on the floor before: the shape check passed on the bullets alone while the sentence
    that gives them their finite verb was never extracted, so a reviewer had to consult wording
    the fragment did not show. Its node is a paragraph, and the bullets keep their own kind.
    """

    spec = _with_bbox(synthetic_clause_spec(), (70.0, 270.0, 524.0, 700.0))

    fragment = extract_clause_fragment(clause_pdf, spec, IDENTITY)

    assert [node.kind for node in fragment.nodes] == ["paragraph", "bullet", "bullet"]
    assert "lead-in" in fragment.nodes[0].raw_text
    assert [node.order for node in fragment.nodes] == [0, 1, 2]
    # The lead-in must not be swallowed into a bullet, nor a bullet into it.
    assert "lead-in" not in fragment.nodes[1].raw_text
    assert "SYMBOL" not in fragment.nodes[0].raw_text


def test_a_bullets_region_without_a_lead_in_gains_no_paragraph_node(clause_pdf) -> None:
    """The narrower region is unchanged, so no other clause's node shape moved."""

    fragment = extract_clause_fragment(clause_pdf, synthetic_clause_spec(), IDENTITY)

    assert [node.kind for node in fragment.nodes] == ["bullet", "bullet"]


def test_extraction_outside_bbox_is_ignored(clause_pdf) -> None:
    fragment = extract_clause_fragment(clause_pdf, synthetic_clause_spec(), IDENTITY)
    assert all("outside" not in node.raw_text for node in fragment.nodes)


def test_quantity_and_unit_tokens_are_typed(clause_pdf) -> None:
    fragment = extract_clause_fragment(clause_pdf, synthetic_clause_spec(), IDENTITY)
    by_kind = {}
    for token in fragment.tokens:
        by_kind.setdefault(token.kind, []).append(token)
    quantities = by_kind["quantity"]
    assert any(token.normalized == Decimal(30) for token in quantities)
    assert any(token.kind == "unit" and token.normalized == "s" for token in fragment.tokens)
    assert any(token.kind == "operator" for token in fragment.tokens)
    assert any(token.kind == "condition" for token in fragment.tokens)


def test_wrong_root_kind_blocks_extraction(clause_pdf) -> None:
    spec = _with_root_kind(synthetic_clause_spec(), "paragraph")
    with pytest.raises(ExtractionError, match="clause structure"):
        extract_clause_fragment(clause_pdf, spec, IDENTITY)


def test_wrapped_paragraph_becomes_one_node_and_extracts_figure_references(tmp_path) -> None:
    path = tmp_path / "paragraph.pdf"
    create_paragraph_clause_pdf(path)
    spec = _with_root_kind(synthetic_clause_spec(), "paragraph")
    with pdfplumber.open(path) as pdf:
        fragment = extract_clause_fragment(pdf, spec, IDENTITY)
    assert len(fragment.nodes) == 1
    assert fragment.nodes[0].kind == "paragraph"
    assert {token.normalized for token in fragment.tokens if token.kind == "reference"} == {
        "figure-5",
        "figure-6",
        "figure-7",
    }


def test_wrong_bbox_blocks_extraction(clause_pdf) -> None:
    spec = _with_bbox(synthetic_clause_spec(), (70.0, 100.0, 524.0, 200.0))
    with pytest.raises(ExtractionError, match="clause structure"):
        extract_clause_fragment(clause_pdf, spec, IDENTITY)


def test_empty_bbox_blocks_extraction(clause_pdf) -> None:
    spec = _with_bbox(synthetic_clause_spec(), (70.0, 750.0, 524.0, 760.0))
    with pytest.raises(ExtractionError, match="clause structure"):
        extract_clause_fragment(clause_pdf, spec, IDENTITY)


def test_fragment_source_carries_clause_provenance(clause_pdf) -> None:
    fragment = extract_clause_fragment(clause_pdf, synthetic_clause_spec(), IDENTITY)
    assert fragment.source.page == 3
    assert fragment.source.clause == "9.9.9"
    assert fragment.source.standard == "SYNTHETIC"
    for node in fragment.nodes:
        assert node.source.clause == "9.9.9"


# --- one clause, several physical segments ------------------------------------------


def test_two_segments_extract_one_fragment_with_per_segment_provenance(segmented_pdf) -> None:
    """A clause is one semantic unit however many regions it occupies."""

    spec = _segmented_spec(FOOT_SEGMENT, HEAD_SEGMENT)
    fragment = extract_clause_fragment(segmented_pdf, spec, IDENTITY)

    assert [node.order for node in fragment.nodes] == [0, 1, 2, 3]
    assert [node.segment_index for node in fragment.nodes] == [0, 0, 1, 1]
    assert [node.source.page for node in fragment.nodes] == [2, 2, 3, 3]
    assert [node.kind for node in fragment.nodes] == ["bullet"] * 4
    # The clause's own source reference is where it starts reading, not where a later
    # segment happens to sit.
    assert fragment.source.page == 2


def test_declared_segment_order_is_reading_order_not_page_order(segmented_pdf) -> None:
    """Two regions of one page may be separated by another clause's, so pages cannot order them."""

    reading_order = extract_clause_fragment(
        segmented_pdf, _segmented_spec(FOOT_SEGMENT, HEAD_SEGMENT), IDENTITY
    )
    reversed_order = extract_clause_fragment(
        segmented_pdf, _segmented_spec(HEAD_SEGMENT, FOOT_SEGMENT), IDENTITY
    )

    assert [node.source.page for node in reversed_order.nodes] == [3, 3, 2, 2]
    assert [node.raw_text for node in reversed_order.nodes] != [
        node.raw_text for node in reading_order.nodes
    ]
    assert reversed_order.raw_sha256 != reading_order.raw_sha256


def test_a_later_segment_may_read_as_another_kind(segmented_pdf) -> None:
    """The root shape is per segment: a bullet list followed by running prose is one clause."""

    spec = _segmented_spec(FOOT_SEGMENT, HEAD_SEGMENT, PROSE_SEGMENT)
    fragment = extract_clause_fragment(segmented_pdf, spec, IDENTITY)

    assert [node.kind for node in fragment.nodes] == ["bullet"] * 4 + ["paragraph"]
    assert fragment.nodes[4].segment_index == 2


def test_a_segment_whose_shape_is_wrong_blocks_and_names_the_segment(segmented_pdf) -> None:
    spec = _segmented_spec(FOOT_SEGMENT, HEAD_SEGMENT, PROSE_SEGMENT).model_copy(
        update={
            "segments": (
                FOOT_SEGMENT,
                HEAD_SEGMENT,
                PROSE_SEGMENT.model_copy(update={"expected_root_kind": "bullets"}),
            )
        }
    )
    with pytest.raises(ExtractionError, match="segment 2"):
        extract_clause_fragment(segmented_pdf, spec, IDENTITY)


def test_the_fragment_digest_covers_the_segment_inventory(segmented_pdf) -> None:
    """Re-declaring a region has to re-open the facts resting on it, text or no text.

    The wider bbox reaches only whitespace, so every node is character-for-character what it
    was. A digest over the nodes alone would call that unchanged and leave a review current
    against a region nobody re-read.
    """

    spec = _segmented_spec(FOOT_SEGMENT, HEAD_SEGMENT)
    widened = _segmented_spec(
        FOOT_SEGMENT.model_copy(update={"expected_bbox": (70.0, 545.0, 540.0, 655.0)}),
        HEAD_SEGMENT,
    )

    original = extract_clause_fragment(segmented_pdf, spec, IDENTITY)
    changed = extract_clause_fragment(segmented_pdf, widened, IDENTITY)

    assert [node.raw_text for node in changed.nodes] == [node.raw_text for node in original.nodes]
    assert changed.segments != original.segments
    assert changed.raw_sha256 != original.raw_sha256


def test_a_one_segment_clause_keeps_the_first_segments_page_as_its_own(clause_pdf) -> None:
    fragment = extract_clause_fragment(clause_pdf, synthetic_clause_spec(), IDENTITY)

    assert all(node.segment_index == 0 for node in fragment.nodes)
    assert {node.source.page for node in fragment.nodes} == {3}
    assert fragment.segments == synthetic_clause_spec().segments
