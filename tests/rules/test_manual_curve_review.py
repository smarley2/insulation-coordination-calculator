# The task brief specifies these exact Decimal string literals.
# ruff: noqa: FURB157

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from insulation_coordination.domain.rules import (
    ApprovalRecord,
    CurvePoint,
    FaultTimeVoltageSelector,
    SourceDocument,
    SourceGeometryReference,
    SourceReference,
)
from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.curves import (
    ManualPlotCalibration,
    RawFigure,
    infer_curve_segments,
    pixel_to_source_point,
    source_point_to_pixel,
)
from insulation_coordination.rules.importer.extract import (
    IMPORTER_VERSION,
    ImportedRuleDraft,
    ImportReviewItem,
    _content_digest,
)
from insulation_coordination.rules.importer.identify import (
    CurveAuditSpec,
    StandardIdentity,
    StandardRecipe,
)
from insulation_coordination.rules.importer.review import (
    replace_manual_curve_variant,
    review_curve_variant,
    set_manual_curve_calibration,
)
from tests.fixtures.synthetic_rules import synthetic_rule_package


def _calibration() -> ManualPlotCalibration:
    return ManualPlotCalibration(
        figure_artifact_sha256="0" * 64,
        left=Decimal("20"),
        top=Decimal("10"),
        right=Decimal("320"),
        bottom=Decimal("210"),
        x_min=Decimal("1"),
        x_max=Decimal("1000"),
        y_min=Decimal("1"),
        y_max=Decimal("100"),
    )


def test_manual_log_calibration_round_trips_without_float() -> None:
    calibration = _calibration()
    point = pixel_to_source_point(Decimal("120"), Decimal("110"), calibration)

    assert point.x == Decimal("10")
    assert point.y == Decimal("10")
    assert source_point_to_pixel(point, calibration) == (
        Decimal("120"),
        Decimal("110"),
    )


@pytest.mark.parametrize(
    ("pixel", "source"),
    (
        ((Decimal("20"), Decimal("10")), (Decimal("1"), Decimal("100"))),
        ((Decimal("320"), Decimal("10")), (Decimal("1000"), Decimal("100"))),
        ((Decimal("20"), Decimal("210")), (Decimal("1"), Decimal("1"))),
        ((Decimal("320"), Decimal("210")), (Decimal("1000"), Decimal("1"))),
    ),
)
def test_manual_log_calibration_round_trips_plot_corners(
    pixel: tuple[Decimal, Decimal],
    source: tuple[Decimal, Decimal],
) -> None:
    calibration = _calibration()
    point = pixel_to_source_point(*pixel, calibration)

    assert (point.x, point.y) == source
    assert source_point_to_pixel(point, calibration) == pixel


def test_segments_are_inferred_from_adjacent_y_values() -> None:
    points = (
        CurvePoint(x=Decimal("1"), y=Decimal("100")),
        CurvePoint(x=Decimal("10"), y=Decimal("100")),
        CurvePoint(x=Decimal("100"), y=Decimal("20")),
        CurvePoint(x=Decimal("1000"), y=Decimal("20")),
    )

    assert tuple(
        (segment.start, segment.end, segment.segment_type, segment.interpolation)
        for segment in infer_curve_segments(points)
    ) == (
        (0, 1, "plateau", "constant"),
        (1, 2, "continuous", "log_log"),
        (2, 3, "plateau", "constant"),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (("right", "20"), ("bottom", "10"), ("x_min", "0"), ("y_max", "1")),
)
def test_manual_calibration_rejects_invalid_bounds(field: str, value: str) -> None:
    payload = _calibration().model_dump(mode="python")
    payload[field] = Decimal(value)
    with pytest.raises(ValueError):
        ManualPlotCalibration.model_validate(payload)


@pytest.mark.parametrize("digest", ("a" + "0" * 64, "0" * 64 + "a"))
def test_manual_calibration_rejects_65_character_hash_variants(digest: str) -> None:
    payload = _calibration().model_dump(mode="python")
    payload["figure_artifact_sha256"] = digest
    with pytest.raises(ValueError):
        ManualPlotCalibration.model_validate(payload)


def test_pixel_conversion_rejects_point_outside_plot() -> None:
    with pytest.raises(ValueError, match="outside reviewed plot rectangle"):
        pixel_to_source_point(Decimal("19"), Decimal("110"), _calibration())


@pytest.fixture
def synthetic_curve_draft(monkeypatch: pytest.MonkeyPatch) -> ImportedRuleDraft:
    identity = StandardIdentity(
        standard="SYNTHETIC",
        edition="1",
        sha256="1" * 64,
        page_count=1,
        recipe_id="synthetic-curves",
    )
    source = SourceReference(
        document_id=identity.recipe_id,
        standard=identity.standard,
        edition=identity.edition,
        page=1,
        figure="5",
    )
    recipe = StandardRecipe(
        id=identity.recipe_id,
        standard=identity.standard,
        edition=identity.edition,
        identity_claim_pattern="",
        expected_page_count=1,
        metadata_identity_fields=(),
        metadata_identity_anchors=(),
        identity_anchors=(),
        tables=(),
        formulas=(),
        mappings=(),
        curves=(
            CurveAuditSpec(
                semantic_id="synthetic.curve",
                figure="5",
                page_number=1,
                expected_bbox=(0.0, 0.0, 400.0, 300.0),
                x_quantity_kind="duration",
                x_unit="s",
                x_source_unit="ms",
                y_quantity_kind="voltage",
                y_unit="V",
                x_scale="log10",
                y_scale="log10",
                variant_slots=(
                    FaultTimeVoltageSelector(
                        subject="conductive_accessible_part",
                        voltage_basis="dc",
                        dvc_context=None,
                        environment_context=None,
                    ),
                    FaultTimeVoltageSelector(
                        subject="conductive_accessible_part",
                        voltage_basis="ac_unspecified",
                        dvc_context=None,
                        environment_context=None,
                    ),
                ),
                permitted_segment_types=("continuous", "plateau"),
                permitted_interpolations=("log_log", "constant"),
            ),
        ),
    )
    monkeypatch.setattr(recipe_registry, "RECIPES", (recipe,))
    figure = RawFigure(
        source=source,
        source_mode="vector_path",
        source_bbox=(Decimal(0), Decimal(0), Decimal(400), Decimal(300)),
        pixel_size=None,
        transform=(
            Decimal(1),
            Decimal(0),
            Decimal(0),
            Decimal(1),
            Decimal(0),
            Decimal(0),
        ),
        ocr_tokens=(),
        traces=(),
        artifact_sha256="0" * 64,
    )
    items = tuple(
        ImportReviewItem(
            code=f"SYNTHETIC_CURVE_REVIEW_{index}",
            semantic_id=f"synthetic.curve.5.{index}",
            kind="curve",
            source=source.model_copy(
                update={"geometry": SourceGeometryReference(artifact_sha256="0" * 64)}
            ),
            expected_contract="Synthetic curve review.",
        )
        for index in (1, 2)
    )
    package = synthetic_rule_package()
    draft = ImportedRuleDraft(
        manifest=package.manifest.model_copy(
            update={
                "approved": False,
                "compatible": False,
                "source_documents": (
                    SourceDocument(
                        id=identity.recipe_id,
                        standard=identity.standard,
                        edition=identity.edition,
                        sha256=identity.sha256,
                    ),
                ),
                "approval_records": (),
            }
        ),
        tables=(),
        formulas=(),
        mappings=(),
        review_items=items,
        raw_grids=(),
        raw_figures=(figure,),
        source_identities=(identity,),
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
        raw_figures=draft.raw_figures,
    )
    recorded_at = datetime(2026, 8, 11, tzinfo=UTC)
    return draft.model_copy(
        update={
            "manifest": draft.manifest.model_copy(
                update={
                    "approval_records": (
                        ApprovalRecord(
                            action="extraction",
                            actor=f"icc-importer/{IMPORTER_VERSION}",
                            recorded_at=recorded_at,
                            notes=f"identity:{identity.recipe_id}",
                        ),
                        ApprovalRecord(
                            action="extraction",
                            actor=f"icc-importer/{IMPORTER_VERSION}",
                            recorded_at=recorded_at,
                            notes=f"layout:{identity.recipe_id}",
                        ),
                        ApprovalRecord(
                            action="extraction",
                            actor=f"icc-importer/{IMPORTER_VERSION}",
                            recorded_at=recorded_at,
                            notes=f"content:{digest}",
                        ),
                    )
                }
            )
        }
    )


def test_manual_variant_replacement_uses_recipe_slot_identity(
    synthetic_curve_draft: ImportedRuleDraft,
) -> None:
    calibrated = set_manual_curve_calibration(
        synthetic_curve_draft,
        figure="5",
        calibration=_calibration(),
        actor="Reviewer",
        notes="Marked synthetic plot rectangle.",
    )
    changed = replace_manual_curve_variant(
        calibrated,
        variant_id="synthetic.curve.5.1",
        source_points=(
            CurvePoint(x=Decimal("1"), y=Decimal("100")),
            CurvePoint(x=Decimal("10"), y=Decimal("100")),
            CurvePoint(x=Decimal("100"), y=Decimal("20")),
            CurvePoint(x=Decimal("1000"), y=Decimal("20")),
        ),
        actor="Reviewer",
        notes="Entered synthetic curve points.",
        input_origin="empty",
    )

    variant = next(variant for rule in changed.curves for variant in rule.variants)
    assert variant.id == "synthetic.curve.5.1"
    assert tuple(segment.interpolation for segment in variant.segments) == (
        "constant",
        "log_log",
        "constant",
    )
    assert not changed.curve_variant_reviews


@pytest.fixture
def reviewed_curve_draft(synthetic_curve_draft: ImportedRuleDraft) -> ImportedRuleDraft:
    calibrated = set_manual_curve_calibration(
        synthetic_curve_draft,
        figure="5",
        calibration=_calibration(),
        actor="Reviewer",
        notes="Marked synthetic plot rectangle.",
    )
    replaced = replace_manual_curve_variant(
        calibrated,
        variant_id="synthetic.curve.5.1",
        source_points=(
            CurvePoint(x=Decimal("1"), y=Decimal("100")),
            CurvePoint(x=Decimal("1000"), y=Decimal("20")),
        ),
        actor="Reviewer",
        notes="Entered synthetic curve points.",
        input_origin="empty",
    )
    return review_curve_variant(
        replaced,
        "synthetic.curve.5.1",
        actor="Reviewer",
        notes="Reviewed synthetic curve points.",
    )


def test_calibration_change_invalidates_all_figure_reviews(
    reviewed_curve_draft: ImportedRuleDraft,
) -> None:
    changed = set_manual_curve_calibration(
        reviewed_curve_draft,
        figure="5",
        calibration=_calibration().model_copy(update={"right": Decimal("321")}),
        actor="Reviewer",
        notes="Corrected synthetic plot corner.",
    )

    assert not tuple(
        review
        for review in changed.curve_variant_reviews
        if review.variant_id.startswith("synthetic.curve.5.")
    )


def test_source_duration_converts_once_to_rule_unit(
    synthetic_curve_draft: ImportedRuleDraft,
) -> None:
    calibrated = set_manual_curve_calibration(
        synthetic_curve_draft,
        figure="5",
        calibration=_calibration(),
        actor="Reviewer",
        notes="Marked synthetic plot rectangle.",
    )
    changed = replace_manual_curve_variant(
        calibrated,
        variant_id="synthetic.curve.5.1",
        source_points=(
            CurvePoint(x=Decimal("1"), y=Decimal("100")),
            CurvePoint(x=Decimal("1000"), y=Decimal("20")),
        ),
        actor="Reviewer",
        notes="Entered synthetic curve points.",
        input_origin="empty",
    )

    variant = changed.curves[0].variants[0]
    assert variant.points[0].x == Decimal("0.001")
    assert variant.points[-1].x == Decimal("1")


@pytest.fixture
def two_reviewed_curve_draft(synthetic_curve_draft: ImportedRuleDraft) -> ImportedRuleDraft:
    calibrated = set_manual_curve_calibration(
        synthetic_curve_draft,
        figure="5",
        calibration=_calibration(),
        actor="Reviewer",
        notes="Marked synthetic plot rectangle.",
    )
    for variant_id, points in (
        (
            "synthetic.curve.5.1",
            (
                CurvePoint(x=Decimal("1"), y=Decimal("100")),
                CurvePoint(x=Decimal("1000"), y=Decimal("20")),
            ),
        ),
        (
            "synthetic.curve.5.2",
            (
                CurvePoint(x=Decimal("1"), y=Decimal("80")),
                CurvePoint(x=Decimal("1000"), y=Decimal("10")),
            ),
        ),
    ):
        calibrated = replace_manual_curve_variant(
            calibrated,
            variant_id=variant_id,
            source_points=points,
            actor="Reviewer",
            notes="Entered synthetic curve points.",
            input_origin="empty",
        )
    for variant_id in ("synthetic.curve.5.1", "synthetic.curve.5.2"):
        calibrated = review_curve_variant(
            calibrated,
            variant_id,
            actor="Reviewer",
            notes="Reviewed synthetic curve points.",
        )
    return calibrated


def test_calibration_edit_reopens_every_affected_curve_review(
    two_reviewed_curve_draft: ImportedRuleDraft,
) -> None:
    changed = set_manual_curve_calibration(
        two_reviewed_curve_draft,
        figure="5",
        calibration=_calibration().model_copy(update={"right": Decimal("321")}),
        actor="Reviewer",
        notes="Corrected synthetic plot corner.",
    )

    assert not changed.curve_variant_reviews
    assert not changed.review_resolutions
    for variant_id in ("synthetic.curve.5.1", "synthetic.curve.5.2"):
        changed = review_curve_variant(
            changed,
            variant_id,
            actor="Reviewer",
            notes="Reviewed after calibration correction.",
        )
    assert {review.variant_id for review in changed.curve_variant_reviews} == {
        "synthetic.curve.5.1",
        "synthetic.curve.5.2",
    }


def test_point_replacement_reopens_only_its_curve_review(
    two_reviewed_curve_draft: ImportedRuleDraft,
) -> None:
    changed = replace_manual_curve_variant(
        two_reviewed_curve_draft,
        variant_id="synthetic.curve.5.1",
        source_points=(
            CurvePoint(x=Decimal("1"), y=Decimal("90")),
            CurvePoint(x=Decimal("1000"), y=Decimal("20")),
        ),
        actor="Reviewer",
        notes="Corrected synthetic curve points.",
        input_origin="empty",
    )

    assert {review.variant_id for review in changed.curve_variant_reviews} == {
        "synthetic.curve.5.2"
    }
    assert {
        item.semantic_id
        for item in changed.review_items
        if item.sha256 in {resolution.review_item_sha256 for resolution in changed.review_resolutions}
    } == {"synthetic.curve.5.2"}
    reviewed = review_curve_variant(
        changed,
        "synthetic.curve.5.1",
        actor="Reviewer",
        notes="Reviewed corrected synthetic curve points.",
    )
    assert {review.variant_id for review in reviewed.curve_variant_reviews} == {
        "synthetic.curve.5.1",
        "synthetic.curve.5.2",
    }


def test_manual_review_records_the_replacement_input_origin(
    synthetic_curve_draft: ImportedRuleDraft,
) -> None:
    calibrated = set_manual_curve_calibration(
        synthetic_curve_draft,
        figure="5",
        calibration=_calibration(),
        actor="Reviewer",
        notes="Marked synthetic plot rectangle.",
    )
    replaced = replace_manual_curve_variant(
        calibrated,
        variant_id="synthetic.curve.5.1",
        source_points=(
            CurvePoint(x=Decimal("1"), y=Decimal("100")),
            CurvePoint(x=Decimal("1000"), y=Decimal("20")),
        ),
        actor="Reviewer",
        notes="Accepted automatic suggestion as a starting point.",
        input_origin="automatic_suggestion",
    )

    reviewed = review_curve_variant(
        replaced,
        "synthetic.curve.5.1",
        actor="Reviewer",
        notes="Reviewed the suggested synthetic curve points.",
    )
    assert reviewed.curve_variant_reviews[0].input_origin == "automatic_suggestion"
