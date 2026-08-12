"""Slice E1 integration: the five verification items project, and nothing else moves.

Synthetic values only. Every subject, condition, and voltage in Tables 26 to 30 belongs to
the licensed source, so this draft is built from the per-table fixtures' invented grids.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from insulation_coordination.domain.rules import (
    ApprovalRecord,
    DecisionRule,
    ProcedureRule,
    SourceReference,
)
from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.extract import (
    IMPORTER_VERSION,
    ImportedRuleDraft,
    ImportReviewItem,
    ImportReviewResolution,
    RawGrid,
    _content_digest,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.iec62477_2022.inventory import (
    DEFERRED_SEMANTIC_IDS,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import (
    RECIPE as IEC_RECIPE,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.verification import (
    DIELECTRIC_SPECS,
    GRID_PROJECTORS,
    TABLE_26,
    TABLE_27_SPECS,
    TABLE_30,
    VERIFICATION_TABLES,
)
from insulation_coordination.rules.importer.review import (
    build_reviewed_draft,
    inventory_report,
)
from tests.fixtures.synthetic_rules import synthetic_rule_package
from tests.rules.importer.iec62477_2022.test_dielectric_tables import (
    _synthetic_grid as _dielectric_grid,
)
from tests.rules.importer.iec62477_2022.test_table26_recipe import IDENTITY
from tests.rules.importer.iec62477_2022.test_table26_recipe import _grid as _table_26_grid
from tests.rules.importer.iec62477_2022.test_table27_recipe import (
    _synthetic_grid as _selection_grid,
)
from tests.rules.importer.iec62477_2022.test_table30_recipe import (
    _synthetic_grid as _table_30_grid,
)

#: The inventory items Slice E1 delivers, and the typed routes each one is expected to
#: contribute. Read off the specs rather than restated, so a route added or renamed in the
#: recipe cannot leave this test asserting yesterday's shape.
PARTIAL_DISCHARGE_APPLICABILITY = f"{ids.TEST_PARTIAL_DISCHARGE}.applicability"
DELIVERED_ITEMS = (
    ids.TEST_IMPULSE_PROCEDURE,
    ids.TEST_IMPULSE_SELECTION,
    ids.TEST_MAINS_DIELECTRIC_VALUES,
    ids.TEST_NON_MAINS_DIELECTRIC_VALUES,
    ids.TEST_PARTIAL_DISCHARGE,
)
SLICE_E1_IDS = frozenset(
    {
        *TABLE_26.decision_route_ids,
        *(spec.semantic_id for spec in TABLE_27_SPECS),
        *(spec.semantic_id for spec in DIELECTRIC_SPECS),
        ids.TEST_PARTIAL_DISCHARGE,
        PARTIAL_DISCHARGE_APPLICABILITY,
    }
)
SOURCE = SourceReference(
    document_id=IDENTITY.recipe_id,
    standard=IDENTITY.standard,
    edition=IDENTITY.edition,
    page=1,
    table="S26",
)


def _slice_e1_grids() -> tuple[RawGrid, ...]:
    """One grid per declared spec: the projector reads whole grids, ``project_table`` reads
    the compacted column selection its own spec declares."""

    return (
        _table_26_grid(),
        _table_30_grid(),
        *(_selection_grid(spec) for spec in TABLE_27_SPECS),
        *(_dielectric_grid(spec) for spec in DIELECTRIC_SPECS),
    )


def _slice_e1_draft(monkeypatch: pytest.MonkeyPatch) -> ImportedRuleDraft:
    """An extracted, fully reviewed draft carrying only the Slice E1 grids."""

    recipe = IEC_RECIPE.model_copy(
        update={
            "standard": IDENTITY.standard,
            "edition": IDENTITY.edition,
            "tables": VERIFICATION_TABLES,
            "formulas": (),
            "mappings": (),
            "clauses": (),
            "curves": (),
            "required_curves": (),
            "grid_projectors": GRID_PROJECTORS,
            "clause_projectors": {},
            "cross_standard_checks": (),
        }
    )
    monkeypatch.setattr(recipe_registry, "RECIPES", (recipe,))
    # One structural review item per declared spec. A projected route's review inventory
    # belongs to the spec it came from, not to the route, so the routes need none of their
    # own.
    review_items = tuple(
        ImportReviewItem(
            code="SYNTHETIC_SLICE_E1_REVIEW",
            semantic_id=spec.semantic_id,
            kind="table",
            source=SOURCE,
            expected_contract=f"synthetic structural review of {spec.semantic_id}",
        )
        for spec in VERIFICATION_TABLES
    )
    resolutions = tuple(
        ImportReviewResolution(
            review_item_sha256=item.sha256,
            actor="Synthetic Source Reviewer",
            recorded_at=datetime(2026, 8, 10, tzinfo=UTC),
            notes="Reviewed the synthetic Slice E1 source artifacts.",
        )
        for item in review_items
    )
    draft = ImportedRuleDraft(
        manifest=synthetic_rule_package().manifest.model_copy(
            update={
                "approved": False,
                "compatible": False,
                "source_documents": (),
                "approval_records": (),
            }
        ),
        tables=(),
        formulas=(),
        mappings=(),
        review_items=review_items,
        review_resolutions=resolutions,
        raw_grids=_slice_e1_grids(),
        source_identities=(IDENTITY,),
    )
    digest = _content_digest(
        draft.tables,
        draft.formulas,
        draft.mappings,
        draft.review_items,
        draft.raw_grids,
        draft.raw_clause_fragments,
        draft.manifest.source_documents,
        draft.source_identities,
        draft.review_resolutions,
    )
    extraction = ApprovalRecord(
        action="extraction",
        actor=f"icc-importer/{IMPORTER_VERSION}",
        recorded_at=datetime(2026, 8, 10, tzinfo=UTC),
        notes=f"content:{digest}",
    )
    return draft.model_copy(
        update={"manifest": draft.manifest.model_copy(update={"approval_records": (extraction,)})}
    )


def _built(monkeypatch: pytest.MonkeyPatch) -> ImportedRuleDraft:
    return build_reviewed_draft(
        _slice_e1_draft(monkeypatch),
        actor="Synthetic Rule Builder",
        notes="Build the Slice E1 verification rules.",
    )


def test_the_build_projects_every_slice_e1_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = _built(monkeypatch)
    typed = (
        {rule.id for rule in built.tables}
        | {rule.id for rule in built.decisions}
        | {rule.id for rule in built.procedures}
    )

    assert SLICE_E1_IDS <= typed
    # Three impulse variants, four impulse-selection routes, eight dielectric routes, the
    # partial-discharge procedure, and its applicability decision.
    assert len(SLICE_E1_IDS) == 3 + 4 + 8 + 1 + 1


def test_procedures_and_decisions_land_in_their_own_collections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The routing guard: ``model_copy`` does not validate, so a ``ProcedureRule`` appended
    to ``decisions`` would sit there undetected until a package failed on the documents."""

    built = _built(monkeypatch)

    assert {rule.id for rule in built.procedures} == {
        *TABLE_26.decision_route_ids,
        ids.TEST_PARTIAL_DISCHARGE,
    }
    assert {rule.id for rule in built.decisions} == {PARTIAL_DISCHARGE_APPLICABILITY}
    assert all(isinstance(rule, ProcedureRule) for rule in built.procedures)
    assert all(isinstance(rule, DecisionRule) for rule in built.decisions)
    # The twelve numeric routes are tables, and neither field table becomes one.
    assert {rule.id for rule in built.tables} == {
        spec.semantic_id for spec in (*TABLE_27_SPECS, *DIELECTRIC_SPECS)
    }
    assert TABLE_30.semantic_id not in {rule.id for rule in built.tables}


def test_the_five_delivered_items_are_typed_and_the_five_e2_items_are_deferred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = {status.semantic_id: status for status in inventory_report(_built(monkeypatch))}

    for semantic_id in DELIVERED_ITEMS:
        status = report[semantic_id]
        assert (status.located, status.extracted, status.typed) == (True, True, True)
        assert status.deferred is False
    for semantic_id in DEFERRED_SEMANTIC_IDS:
        assert report[semantic_id].deferred is True
        assert report[semantic_id].typed is False


def test_only_the_five_e2_test_items_remain_deferred() -> None:
    #: E2 removes each identifier as it delivers it, so the count only ever shrinks from the
    #: five this slice inherited.
    assert len(DEFERRED_SEMANTIC_IDS) <= 5
    assert all(
        semantic_id.startswith("iec62477_2022.test.") for semantic_id in DEFERRED_SEMANTIC_IDS
    )
    assert DEFERRED_SEMANTIC_IDS.isdisjoint(DELIVERED_ITEMS)
