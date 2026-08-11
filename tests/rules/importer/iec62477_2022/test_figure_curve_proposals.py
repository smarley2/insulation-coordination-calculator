"""Figure 5–7 semantic association into proposed curve rules. Synthetic only."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pypdf import PdfWriter

from insulation_coordination.domain.rules import (
    CurveAxis,
    CurvePoint,
    CurveSegment,
    FaultTimeVoltageSelector,
    FaultTimeVoltageVariant,
    SourceReference,
)
from insulation_coordination.rules.evaluator import (
    evaluate_piecewise_curve,
    select_curve_variant,
)
from insulation_coordination.rules.importer.curves import (
    ConservatismReport,
    CurveDigitizationResult,
    RawFigure,
)
from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    _extract_curve_artifacts,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.identify import StandardIdentity
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import RECIPE
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.curves import CURVES
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.projection import (
    project_fault_time_voltage,
)
from insulation_coordination.rules.importer.review import _current_source_artifact_sha256

SOURCE = SourceReference(
    document_id="synthetic-curves",
    standard="SYNTHETIC",
    edition="1",
    page=54,
    figure="SF-5",
)
IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="9" * 64,
    page_count=56,
    recipe_id="synthetic-curves",
)


def _figure(figure: str, page: int, digest: str) -> RawFigure:
    return RawFigure(
        source=SOURCE.model_copy(update={"figure": figure, "page": page}),
        source_mode="vector_path",
        source_bbox=(Decimal(70), Decimal(120), Decimal(524), Decimal(700)),
        pixel_size=None,
        transform=(Decimal(1), Decimal(0), Decimal(0), Decimal(1), Decimal(0), Decimal(0)),
        ocr_tokens=(),
        traces=(),
        artifact_sha256=digest,
    )


def _variant(
    suffix: str,
    subject: str,
    basis: str,
    dvc: str | None,
    env: str | None,
    artifact: str,
) -> FaultTimeVoltageVariant:
    figure_by_artifact = {
        "a" * 64: ("SF-5", 54),
        "b" * 64: ("SF-6", 55),
        "c" * 64: ("SF-7", 56),
        "d" * 64: ("SF-5", 54),
    }
    figure, page = figure_by_artifact[artifact]
    return FaultTimeVoltageVariant(
        id=f"{ids.DVC_FAULT_TIME_VOLTAGE}.{suffix}",
        selector=FaultTimeVoltageSelector(
            subject=subject,
            voltage_basis=basis,
            dvc_context=dvc,
            environment_context=env,
        ),
        x_axis=CurveAxis(
            quantity_kind="duration",
            unit="s",
            scale="log10",
            minimum=Decimal(1),
            maximum=Decimal(100),
        ),
        y_axis=CurveAxis(
            quantity_kind="voltage",
            unit="V",
            scale="log10",
            minimum=Decimal(10),
            maximum=Decimal(1000),
        ),
        points=(
            CurvePoint(x=Decimal(1), y=Decimal(100)),
            CurvePoint(x=Decimal(10), y=Decimal(50)),
            CurvePoint(x=Decimal(100), y=Decimal(20)),
        ),
        segments=(
            CurveSegment(start=0, end=1, segment_type="continuous", interpolation="log_log"),
            CurveSegment(start=1, end=2, segment_type="continuous", interpolation="log_log"),
        ),
        applicability="review required",
        source=SOURCE.model_copy(update={"figure": figure, "page": page}),
        reviewed_artifact_sha256=artifact,
    )


def _figures() -> tuple[RawFigure, RawFigure, RawFigure]:
    return (
        _figure("SF-5", 54, "a" * 64),
        _figure("SF-6", 55, "b" * 64),
        _figure("SF-7", 56, "c" * 64),
    )


def _variants(figure_index: int, artifact: str) -> tuple[FaultTimeVoltageVariant, ...]:
    return tuple(
        _variant(
            f"{CURVES[figure_index].figure}.{index}",
            selector.subject,
            selector.voltage_basis,
            selector.dvc_context,
            selector.environment_context,
            artifact,
        )
        for index, selector in enumerate(CURVES[figure_index].variant_slots, start=1)
    )


def test_projected_variants_have_exact_distinct_selectors() -> None:
    rule, proposals = project_fault_time_voltage(
        _figures(),
        _variants(0, "a" * 64),
        _variants(1, "b" * 64),
        _variants(2, "c" * 64),
        IDENTITY,
    )
    assert rule.id == ids.DVC_FAULT_TIME_VOLTAGE
    selectors = {variant.selector for variant in rule.variants}
    assert len(selectors) == len(rule.variants) == 8
    assert len(proposals) == 1
    assert proposals[0].semantic_id == ids.DVC_FAULT_TIME_VOLTAGE
    assert proposals[0].state == "proposed"
    assert proposals[0].rule_sha256 == canonical_model_sha256(rule)


def test_figure_subjects_and_none_dimensions_are_exact() -> None:
    rule, _ = project_fault_time_voltage(
        _figures(),
        _variants(0, "a" * 64),
        _variants(1, "b" * 64),
        _variants(2, "c" * 64),
        IDENTITY,
    )
    assert all(
        variant.selector.subject == "accessible_circuit"
        for variant in rule.variants[:6]
    )
    assert all(
        variant.selector.subject == "conductive_accessible_part"
        and variant.selector.dvc_context is None
        and variant.selector.environment_context is None
        for variant in rule.variants[6:]
    )


def test_none_dimensions_do_not_wildcard() -> None:
    rule, _ = project_fault_time_voltage(
        _figures(),
        _variants(0, "a" * 64),
        _variants(1, "b" * 64),
        _variants(2, "c" * 64),
        IDENTITY,
    )
    # A selector with a DVC context must NOT match the variant whose context is None.
    probe = FaultTimeVoltageSelector(
        subject="conductive_accessible_part",
        voltage_basis="ac_unspecified",
        dvc_context="dvc-a",
        environment_context=None,
    )
    selection = select_curve_variant(rule, probe)
    assert selection.variant is None


@pytest.mark.parametrize("basis", ["ac_rms", "ac_peak"])
def test_figure_7_refuses_a_more_specific_ac_basis(basis: str) -> None:
    """Selection is exact, so the refusal needs no evaluator machinery.

    Figure 7 identifies the variant as AC without specifying RMS or peak. Therefore the
    semantic contract uses ``ac_unspecified`` and consumers must not infer a more specific
    basis.

    This guards selection, not comparison: it does not prove a consumer cannot select
    ``ac_unspecified`` and then compare the returned number against an RMS or peak
    quantity. #36 and #37 add that consumer-level guard when they add engineering
    comparisons.
    """
    rule, _ = project_fault_time_voltage(
        _figures(),
        _variants(0, "a" * 64),
        _variants(1, "b" * 64),
        _variants(2, "c" * 64),
        IDENTITY,
    )
    probe = FaultTimeVoltageSelector(
        subject="conductive_accessible_part",
        voltage_basis=basis,
        dvc_context=None,
        environment_context=None,
    )

    assert select_curve_variant(rule, probe).variant is None


def test_exact_selector_evaluates_matching_variant() -> None:
    rule, _ = project_fault_time_voltage(
        _figures(),
        _variants(0, "a" * 64),
        _variants(1, "b" * 64),
        _variants(2, "c" * 64),
        IDENTITY,
    )
    result = evaluate_piecewise_curve(
        rule,
        FaultTimeVoltageSelector(
            subject="conductive_accessible_part",
            voltage_basis="ac_unspecified",
            dvc_context=None,
            environment_context=None,
        ),
        Decimal(10),
    )
    assert result.status == "matched"
    assert result.variant_id == f"{ids.DVC_FAULT_TIME_VOLTAGE}.7.2"


def test_aggregate_artifact_hash_covers_ordered_figure_digests() -> None:
    _, first = project_fault_time_voltage(
        _figures(),
        _variants(0, "a" * 64),
        _variants(1, "b" * 64),
        _variants(2, "c" * 64),
        IDENTITY,
    )
    _, second = project_fault_time_voltage(
        (_figure("SF-5", 54, "d" * 64), *_figures()[1:]),
        _variants(0, "d" * 64),
        _variants(1, "b" * 64),
        _variants(2, "c" * 64),
        IDENTITY,
    )
    assert first[0].source_artifact_sha256 != second[0].source_artifact_sha256


def test_projected_source_hash_matches_review_gate() -> None:
    rule, proposals = project_fault_time_voltage(
        _figures(),
        _variants(0, "a" * 64),
        _variants(1, "b" * 64),
        _variants(2, "c" * 64),
        IDENTITY,
    )
    draft = ImportedRuleDraft.model_construct(
        tables=(),
        formulas=(),
        mappings=(),
        decisions=(),
        procedures=(),
        guidance=(),
        curves=(rule,),
    )
    assert proposals[0].source_artifact_sha256 == _current_source_artifact_sha256(
        draft, proposals[0]
    )


def test_variant_must_be_linked_to_its_figure_artifact() -> None:
    figure5 = _variants(0, "a" * 64)
    figure5 = (
        figure5[0].model_copy(update={"reviewed_artifact_sha256": "b" * 64}),
        *figure5[1:],
    )
    with pytest.raises(ValueError, match="Figure 5 variant"):
        project_fault_time_voltage(
            _figures(),
            figure5,
            _variants(1, "b" * 64),
            _variants(2, "c" * 64),
            IDENTITY,
        )


def test_missing_figure_blocks_projection() -> None:
    with pytest.raises(ValueError, match="Figure"):
        project_fault_time_voltage(
            _figures()[:2],
            _variants(0, "a" * 64),
            _variants(1, "b" * 64),
            (),
            IDENTITY,
        )


def test_incomplete_variant_group_blocks_projection() -> None:
    with pytest.raises(ValueError, match="exact reviewed variant inventory"):
        project_fault_time_voltage(
            _figures(),
            _variants(0, "a" * 64),
            (),
            _variants(2, "c" * 64),
            IDENTITY,
        )


def test_wrong_figure_semantic_role_blocks_projection() -> None:
    figure6 = _variants(1, "b" * 64)
    figure6 = (
        figure6[0].model_copy(
            update={
                "selector": figure6[0].selector.model_copy(
                    update={"subject": "conductive_accessible_part"}
                )
            }
        ),
        *figure6[1:],
    )
    with pytest.raises(ValueError, match="exact reviewed variant inventory"):
        project_fault_time_voltage(
            _figures(),
            _variants(0, "a" * 64),
            figure6,
            _variants(2, "c" * 64),
            IDENTITY,
        )


def test_real_extraction_stage_projects_all_recipe_figures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "synthetic-56-pages.pdf"
    writer = PdfWriter()
    for _ in range(56):
        writer.add_blank_page(width=612, height=792)
    with path.open("wb") as stream:
        writer.write(stream)

    artifacts = {"5": "a" * 64, "6": "b" * 64, "7": "c" * 64}

    def fake_extract(_reader_page, _plumber_page, spec, _ocr, identity):
        return _figure(spec.figure, spec.page_number, artifacts[spec.figure]).model_copy(
            update={
                "source": SOURCE.model_copy(
                    update={
                        "document_id": identity.recipe_id,
                        "standard": identity.standard,
                        "edition": identity.edition,
                        "page": spec.page_number,
                        "figure": spec.figure,
                    }
                )
            }
        )

    def fake_digitize(figure, spec, _ocr, _identity):
        variants = tuple(
            _variant(
                f"{spec.figure}.{index}",
                selector.subject,
                selector.voltage_basis,
                selector.dvc_context,
                selector.environment_context,
                figure.artifact_sha256,
            ).model_copy(update={"source": figure.source})
            for index, selector in enumerate(spec.variant_slots, start=1)
        )
        from insulation_coordination.domain.rules import PiecewiseCurveRule

        return CurveDigitizationResult(
            proposed_rule=PiecewiseCurveRule(
                id=ids.DVC_FAULT_TIME_VOLTAGE,
                variants=variants,
                source=figure.source,
            ),
            calibration=None,
            conservatism=ConservatismReport(
                maximum_positive_voltage_error=Decimal(0),
                maximum_fidelity_error_pixels=Decimal(0),
                proven=True,
            ),
            blocking_review_items=(),
        )

    monkeypatch.setattr(
        "insulation_coordination.rules.importer.curves.extract_raw_figure", fake_extract
    )
    monkeypatch.setattr(
        "insulation_coordination.rules.importer.curves.digitize_curve_figure", fake_digitize
    )
    figures, digitizations, curves, proposals, review_items = _extract_curve_artifacts(
        path, IDENTITY.model_copy(update={"recipe_id": "iec62477-1-2022"}), RECIPE, object()
    )
    assert len(figures) == len(digitizations) == 3
    assert len(curves) == len(proposals) == 1
    assert curves[0].id == ids.DVC_FAULT_TIME_VOLTAGE
    assert len(review_items) == 8
    assert {item.semantic_id for item in review_items} == {
        variant.id for variant in curves[0].variants
    }
