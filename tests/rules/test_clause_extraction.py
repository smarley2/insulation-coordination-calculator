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
from insulation_coordination.rules.importer.identify import ClauseAuditSpec, StandardIdentity
from tests.fixtures.synthetic_pdf import create_clause_pdf, create_paragraph_clause_pdf

IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="4" * 64,
    page_count=3,
    recipe_id="synthetic-clause",
)
BBOX = (70.0, 300.0, 524.0, 700.0)


def synthetic_clause_spec() -> ClauseAuditSpec:
    return ClauseAuditSpec(
        semantic_id="synthetic.clause.applicability",
        clause="9.9.9",
        page_number=3,
        expected_bbox=BBOX,
        expected_root_kind="bullets",
        output_kind="decision",
    )


def _page(path):
    with pdfplumber.open(path) as pdf:
        yield pdf.pages[2]


@pytest.fixture
def clause_page(tmp_path):
    path = tmp_path / "clause.pdf"
    create_clause_pdf(path)
    with pdfplumber.open(path) as pdf:
        yield pdf.pages[2]


def test_extracts_nodes_in_reading_order_with_page_provenance(clause_page) -> None:
    fragment = extract_clause_fragment(clause_page, synthetic_clause_spec(), IDENTITY)
    assert [node.order for node in fragment.nodes] == list(range(len(fragment.nodes)))
    assert all(token.source.page == 3 for token in fragment.tokens)
    assert fragment.id == "raw-synthetic.clause.applicability"
    assert all(node.kind == "bullet" for node in fragment.nodes)


def test_fragment_hash_is_stable(clause_page) -> None:
    first = extract_clause_fragment(clause_page, synthetic_clause_spec(), IDENTITY)
    second = extract_clause_fragment(clause_page, synthetic_clause_spec(), IDENTITY)
    assert first.raw_sha256 == second.raw_sha256
    assert len(first.raw_sha256) == 64


def test_normalization_preserves_hash_spans_and_merges_wrapped_lines(clause_page) -> None:
    fragment = extract_clause_fragment(clause_page, synthetic_clause_spec(), IDENTITY)
    normalized = normalize_clause_fragment(fragment)
    assert normalized.raw_sha256 == fragment.raw_sha256
    assert [node.order for node in normalized.nodes] == list(
        range(len(normalized.nodes))
    )
    # The second bullet wraps across two physical lines; normalization merges them.
    assert len(normalized.nodes) == 2
    assert "wrapped" in normalized.nodes[1].raw_text
    assert "continues" in normalized.nodes[1].raw_text
    assert normalized.tokens == fragment.tokens


def test_extraction_outside_bbox_is_ignored(clause_page) -> None:
    fragment = extract_clause_fragment(clause_page, synthetic_clause_spec(), IDENTITY)
    assert all("outside" not in node.raw_text for node in fragment.nodes)


def test_quantity_and_unit_tokens_are_typed(clause_page) -> None:
    fragment = extract_clause_fragment(clause_page, synthetic_clause_spec(), IDENTITY)
    by_kind = {}
    for token in fragment.tokens:
        by_kind.setdefault(token.kind, []).append(token)
    quantities = by_kind["quantity"]
    assert any(token.normalized == Decimal(30) for token in quantities)
    assert any(token.kind == "unit" and token.normalized == "s" for token in fragment.tokens)
    assert any(token.kind == "operator" for token in fragment.tokens)
    assert any(token.kind == "condition" for token in fragment.tokens)


def test_wrong_root_kind_blocks_extraction(clause_page) -> None:
    spec = synthetic_clause_spec().model_copy(update={"expected_root_kind": "paragraph"})
    with pytest.raises(ExtractionError, match="clause structure"):
        extract_clause_fragment(clause_page, spec, IDENTITY)


def test_wrapped_paragraph_becomes_one_node_and_extracts_figure_references(tmp_path) -> None:
    path = tmp_path / "paragraph.pdf"
    create_paragraph_clause_pdf(path)
    spec = synthetic_clause_spec().model_copy(update={"expected_root_kind": "paragraph"})
    with pdfplumber.open(path) as pdf:
        fragment = extract_clause_fragment(pdf.pages[2], spec, IDENTITY)
    assert len(fragment.nodes) == 1
    assert fragment.nodes[0].kind == "paragraph"
    assert {
        token.normalized for token in fragment.tokens if token.kind == "reference"
    } == {"figure-5", "figure-6", "figure-7"}


def test_wrong_bbox_blocks_extraction(clause_page) -> None:
    spec = synthetic_clause_spec().model_copy(
        update={"expected_bbox": (70.0, 100.0, 524.0, 200.0)}
    )
    with pytest.raises(ExtractionError, match="clause structure"):
        extract_clause_fragment(clause_page, spec, IDENTITY)


def test_empty_bbox_blocks_extraction(clause_page) -> None:
    spec = synthetic_clause_spec().model_copy(
        update={"expected_bbox": (70.0, 750.0, 524.0, 760.0)}
    )
    with pytest.raises(ExtractionError, match="clause structure"):
        extract_clause_fragment(clause_page, spec, IDENTITY)


def test_fragment_source_carries_clause_provenance(clause_page) -> None:
    fragment = extract_clause_fragment(clause_page, synthetic_clause_spec(), IDENTITY)
    assert fragment.source.page == 3
    assert fragment.source.clause == "9.9.9"
    assert fragment.source.standard == "SYNTHETIC"
    for node in fragment.nodes:
        assert node.source.clause == "9.9.9"
