"""Private structural and determinism checks for IEC 62477 Figures 5-7.

All source values remain in the maintainer-supplied PDFs.  These tests compare only
canonical hashes and stable semantic identities; they never snapshot extracted data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from insulation_coordination.rules.importer.approval import approval_blockers
from insulation_coordination.rules.importer.extract import (
    _REQUIRED_RECIPES,
    canonical_model_sha256,
    extract_draft,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids

pytestmark = pytest.mark.private_standard


def _paths(supplied_standards: dict[str, Path]) -> tuple[Path, ...]:
    return tuple(supplied_standards[recipe] for recipe in sorted(_REQUIRED_RECIPES))


#: The reviewed variant inventory, per figure, as
#: ``(subject, voltage_basis, dvc_context, environment_context)``. Stated here
#: independently of the curve recipe so that the two can disagree: an edit to one figure's
#: declared slots must not be able to redefine another figure's silently.
#:
#: Structural only. These are the neutral semantic identities the contract is built from —
#: no curve coordinate, no value and no wording from the document appears here, which is
#: why this inventory is safe to hold in a test at all.
_EXPECTED_SELECTORS: dict[str, tuple[tuple[str, str, str | None, str | None], ...]] = {
    "5": (
        ("accessible_circuit", "dc", "b", "dry"),
        ("accessible_circuit", "dc", "as", "dry"),
        ("accessible_circuit", "dc", "as", "wet_and_saltwater_wet"),
    ),
    "6": (
        ("accessible_circuit", "ac_peak", "b", "dry"),
        ("accessible_circuit", "ac_peak", "as", "dry"),
        ("accessible_circuit", "ac_peak", "as", "wet_and_saltwater_wet"),
    ),
    # Figure 7 identifies the variant as AC without specifying RMS or peak. Therefore the
    # semantic contract uses ac_unspecified and consumers must not infer a more specific
    # basis.
    "7": (
        ("conductive_accessible_part", "dc", None, None),
        ("conductive_accessible_part", "ac_unspecified", None, None),
    ),
}


def _selectors_by_figure(draft) -> dict[str, tuple[tuple[str, str, str | None, str | None], ...]]:
    rule = next(
        (item for item in draft.curves if item.id == ids.DVC_FAULT_TIME_VOLTAGE), None
    )
    assert rule is not None, (
        "the draft carries no aggregate fault-time voltage rule; a blocking curve review "
        "item suppresses the projection, so check those first"
    )
    grouped: dict[str, tuple[tuple[str, str, str | None, str | None], ...]] = {}
    for variant in rule.variants:
        figure = variant.source.figure
        assert figure is not None, f"variant {variant.id} lost its figure provenance"
        grouped[figure] = (
            *grouped.get(figure, ()),
            (
                variant.selector.subject,
                variant.selector.voltage_basis,
                variant.selector.dvc_context,
                variant.selector.environment_context,
            ),
        )
    return grouped


def _curve_artifact_hashes(draft) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        tuple(canonical_model_sha256(figure) for figure in draft.raw_figures),
        tuple(canonical_model_sha256(result) for result in draft.curve_digitizations),
    )


def test_figures_5_to_7_digitize_deterministically(
    extracted_draft,
    supplied_paths: tuple[Path, ...],
) -> None:
    """The shared import against a second, independent one: that comparison is the point."""

    first = extracted_draft
    second = extract_draft(supplied_paths)

    assert {figure.source.figure for figure in first.raw_figures} == {"5", "6", "7"}
    assert len(first.curve_digitizations) == 3
    assert all(not result.blocking_review_items for result in first.curve_digitizations)
    assert _curve_artifact_hashes(first) == _curve_artifact_hashes(second)


def test_reviewed_variant_inventory_carries_the_expected_selectors(extracted_draft) -> None:
    """What the licensed documents actually project, checked against the reviewed inventory.

    The public recipe test checks what the recipe declares. This checks what comes out of
    the real extraction and projection, which is the artifact a package is built from, and
    it is the assertion that keeps a future edit to one figure from silently redefining
    another.
    """

    assert _selectors_by_figure(extracted_draft) == _EXPECTED_SELECTORS


def test_figure_7_ac_variant_states_an_unspecified_basis(extracted_draft) -> None:
    """Figure 7 identifies the variant as AC without specifying RMS or peak.

    Therefore the semantic contract uses ``ac_unspecified`` and consumers must not infer a
    more specific basis. Asserted on its own, and not only through the inventory above,
    because this one token is the whole subject of the change and a reader looking for it
    should not have to spot it inside a larger comparison.
    """

    bases = tuple(basis for _subject, basis, _dvc, _env in _selectors_by_figure(extracted_draft)["7"])

    assert bases == ("dc", "ac_unspecified")


def test_unreviewed_curve_proposal_blocks_initial_approval(extracted_draft) -> None:
    draft = extracted_draft
    proposal = next(
        item
        for item in draft.semantic_proposals
        if item.semantic_id == ids.DVC_FAULT_TIME_VOLTAGE
    )

    assert proposal.state == "proposed"
    assert any(
        item.code == "CURVE_VARIANT_REVIEW_REQUIRED"
        for item in approval_blockers(draft)
    )
