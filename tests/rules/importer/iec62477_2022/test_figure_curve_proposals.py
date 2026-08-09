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


def test_projected_variants_have_exact_distinct_selectors() -> None:
    rule, proposals = project_fault_time_voltage(
        _figures(), (_variant("ac", "accessible_circuit", "ac_rms", "dvc-a", "indoor", "a" * 64),),
        (_variant("dc", "accessible_circuit", "dc", "dvc-a", "indoor", "b" * 64),),
        (_variant("peak", "conductive_accessible_part", "ac_peak", None, None, "c" * 64),),
        IDENTITY,
    )
    assert rule.id == ids.DVC_FAULT_TIME_VOLTAGE
    selectors = {variant.selector for variant in rule.variants}
    assert len(selectors) == len(rule.variants) == 3
    assert len(proposals) == 1
    assert proposals[0].semantic_id == ids.DVC_FAULT_TIME_VOLTAGE
    assert proposals[0].state == "proposed"
    assert proposals[0].rule_sha256 == canonical_model_sha256(rule)


def test_figure_subjects_and_none_dimensions_are_exact() -> None:
    rule, _ = project_fault_time_voltage(
        _figures(),
        (_variant("ac", "accessible_circuit", "ac_rms", "dvc-a", "indoor", "a" * 64),),
        (_variant("dc", "accessible_circuit", "dc", "dvc-a", "indoor", "b" * 64),),
        (_variant("peak", "conductive_accessible_part", "ac_peak", None, None, "c" * 64),),
        IDENTITY,
    )
    by_id = {variant.id: variant for variant in rule.variants}
    assert by_id[f"{ids.DVC_FAULT_TIME_VOLTAGE}.ac"].selector.subject == "accessible_circuit"
    assert (
        by_id[f"{ids.DVC_FAULT_TIME_VOLTAGE}.peak"].selector.subject
        == "conductive_accessible_part"
    )
    peak = by_id[f"{ids.DVC_FAULT_TIME_VOLTAGE}.peak"].selector
    assert peak.dvc_context is None and peak.environment_context is None


def test_none_dimensions_do_not_wildcard() -> None:
    rule, _ = project_fault_time_voltage(
        _figures(),
        (_variant("ac", "accessible_circuit", "ac_rms", "dvc-a", "indoor", "a" * 64),),
        (_variant("dc", "accessible_circuit", "dc", "dvc-a", "indoor", "b" * 64),),
        (_variant("peak", "conductive_accessible_part", "ac_peak", None, None, "c" * 64),),
        IDENTITY,
    )
    # A selector with a DVC context must NOT match the variant whose context is None.
    probe = FaultTimeVoltageSelector(
        subject="conductive_accessible_part",
        voltage_basis="ac_peak",
        dvc_context="dvc-a",
        environment_context=None,
    )
    selection = select_curve_variant(rule, probe)
    assert selection.variant is None


def test_exact_selector_evaluates_matching_variant() -> None:
    rule, _ = project_fault_time_voltage(
        _figures(),
        (_variant("ac", "accessible_circuit", "ac_rms", "dvc-a", "indoor", "a" * 64),),
        (_variant("dc", "accessible_circuit", "dc", "dvc-a", "indoor", "b" * 64),),
        (_variant("peak", "conductive_accessible_part", "ac_peak", None, None, "c" * 64),),
        IDENTITY,
    )
    result = evaluate_piecewise_curve(
        rule,
        FaultTimeVoltageSelector(
            subject="conductive_accessible_part",
            voltage_basis="ac_peak",
            dvc_context=None,
            environment_context=None,
        ),
        Decimal(10),
    )
    assert result.status == "matched"
    assert result.variant_id == f"{ids.DVC_FAULT_TIME_VOLTAGE}.peak"


def test_aggregate_artifact_hash_covers_ordered_figure_digests() -> None:
    _, first = project_fault_time_voltage(
        _figures(),
        (_variant("ac", "accessible_circuit", "ac_rms", "dvc-a", "indoor", "a" * 64),),
        (_variant("dc", "accessible_circuit", "dc", "dvc-a", "indoor", "b" * 64),),
        (_variant("peak", "conductive_accessible_part", "ac_peak", None, None, "c" * 64),),
        IDENTITY,
    )
    _, second = project_fault_time_voltage(
        (_figure("SF-5", 54, "d" * 64), *_figures()[1:]),
        (_variant("ac", "accessible_circuit", "ac_rms", "dvc-a", "indoor", "d" * 64),),
        (_variant("dc", "accessible_circuit", "dc", "dvc-a", "indoor", "b" * 64),),
        (_variant("peak", "conductive_accessible_part", "ac_peak", None, None, "c" * 64),),
        IDENTITY,
    )
    assert first[0].source_artifact_sha256 != second[0].source_artifact_sha256


def test_projected_source_hash_matches_review_gate() -> None:
    rule, proposals = project_fault_time_voltage(
        _figures(),
        (_variant("ac", "accessible_circuit", "ac_rms", "dvc-a", "indoor", "a" * 64),),
        (_variant("dc", "accessible_circuit", "dc", "dvc-a", "indoor", "b" * 64),),
        (_variant("peak", "conductive_accessible_part", "ac_peak", None, None, "c" * 64),),
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
    with pytest.raises(ValueError, match="Figure 5 variant"):
        project_fault_time_voltage(
            _figures(),
            (_variant("ac", "accessible_circuit", "ac_rms", "dvc-a", "indoor", "b" * 64),),
            (_variant("dc", "accessible_circuit", "dc", "dvc-a", "indoor", "b" * 64),),
            (_variant("peak", "conductive_accessible_part", "ac_peak", None, None, "c" * 64),),
            IDENTITY,
        )


def test_missing_figure_blocks_projection() -> None:
    with pytest.raises(ValueError, match="Figure"):
        project_fault_time_voltage(
            _figures()[:2],
            (_variant("ac", "accessible_circuit", "ac_rms", "dvc-a", "indoor", "a" * 64),),
            (_variant("dc", "accessible_circuit", "dc", "dvc-a", "indoor", "b" * 64),),
            (),
            IDENTITY,
        )


def test_empty_variant_group_blocks_projection() -> None:
    with pytest.raises(ValueError, match="each require exactly one"):
        project_fault_time_voltage(
            _figures(),
            (_variant("ac", "accessible_circuit", "ac_rms", "dvc-a", "indoor", "a" * 64),),
            (),
            (_variant("peak", "conductive_accessible_part", "ac_peak", None, None, "c" * 64),),
            IDENTITY,
        )


def test_wrong_figure_semantic_role_blocks_projection() -> None:
    with pytest.raises(ValueError, match="Figure 6 variant has the wrong semantic role"):
        project_fault_time_voltage(
            _figures(),
            (_variant("ac", "accessible_circuit", "ac_rms", "dvc-a", "indoor", "a" * 64),),
            (_variant("peak", "accessible_circuit", "ac_peak", "dvc-a", "indoor", "b" * 64),),
            (_variant("peak", "conductive_accessible_part", "ac_peak", None, None, "c" * 64),),
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
        suffix = {"5": "ac", "6": "dc", "7": "peak"}[spec.figure]
        variant = _variant(
            suffix,
            spec.variant_slots[0].subject,
            spec.variant_slots[0].voltage_basis,
            spec.variant_slots[0].dvc_context,
            spec.variant_slots[0].environment_context,
            figure.artifact_sha256,
        ).model_copy(
            update={
                "id": f"{ids.DVC_FAULT_TIME_VOLTAGE}.{spec.figure}",
                "source": figure.source,
            }
        )
        from insulation_coordination.domain.rules import PiecewiseCurveRule

        return CurveDigitizationResult(
            proposed_rule=PiecewiseCurveRule(
                id=ids.DVC_FAULT_TIME_VOLTAGE,
                variants=(variant,),
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
    figures, digitizations, curves, proposals, blockers = _extract_curve_artifacts(
        path, IDENTITY.model_copy(update={"recipe_id": "iec62477-1-2022"}), RECIPE, object()
    )
    assert len(figures) == len(digitizations) == 3
    assert len(curves) == len(proposals) == 1
    assert curves[0].id == ids.DVC_FAULT_TIME_VOLTAGE
    assert blockers == ()
