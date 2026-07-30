from uuid import UUID

import pytest
from pydantic import ValidationError

from insulation_coordination.calculation.grouping import calculation_signature
from insulation_coordination.domain.rules import SourceReference
from insulation_coordination.report.latex import render_latex
from insulation_coordination.report.model import ReportBuildError, build_report_model


@pytest.fixture
def report_model(report_inputs):
    return build_report_model(*report_inputs)


def test_report_renders_symbolic_and_substituted_formula(report_model) -> None:
    tex = render_latex(report_model)

    assert r"y = y_0 + \frac{(x-x_0)(y_1-y_0)}{x_1-x_0}" in tex
    assert r"150\,\mathrm{V}" in tex
    assert r"100\,\mathrm{V}" in tex
    assert "SYNTHETIC-PART-1:1, synthetic, Table synthetic-distance" in tex
    assert "entire synthetic table" not in tex
    assert r"\mathrm{steady\_state\_peak}" in tex
    assert r"\max(impulse, steady_state_peak)" not in tex


def test_report_escapes_user_text_without_escaping_trusted_formula(report_model) -> None:
    tex = render_latex(report_model)

    assert r"\textbackslash{}input\{unsafe\}\&" in tex
    assert r"HV\_1" in tex
    assert r"LV\%2" in tex
    assert r"\frac{" in tex
    assert r"\input{unsafe}" not in tex


def test_report_snapshot_is_frozen_and_deterministic(report_inputs) -> None:
    first = build_report_model(*report_inputs)
    second = build_report_model(*report_inputs)

    assert first == second
    assert render_latex(first) == render_latex(second)
    with pytest.raises(ValidationError, match="frozen"):
        first.project_title = "changed"


def test_report_rejects_missing_extra_duplicate_and_stale_results(report_inputs) -> None:
    project, results, groups, rules = report_inputs
    result = results[0]

    with pytest.raises(ReportBuildError, match="missing"):
        build_report_model(project, (), (), rules)
    with pytest.raises(ReportBuildError, match="duplicate"):
        build_report_model(project, (result, result), groups, rules)
    with pytest.raises(ReportBuildError, match="extra"):
        build_report_model(
            project,
            (result.model_copy(update={"pair_id": UUID(int=99)}),),
            groups,
            rules,
        )
    with pytest.raises(ReportBuildError, match="effective input"):
        build_report_model(
            project,
            (
                result.model_copy(
                    update={
                        "effective_inputs": result.effective_inputs.model_copy(
                            update={
                                "frequency_hz": result.effective_inputs.frequency_hz.model_copy(
                                    update={"value": result.effective_inputs.frequency_hz.value + 1}
                                )
                            }
                        )
                    }
                ),
            ),
            groups,
            rules,
        )


def test_report_rejects_rule_engine_hash_and_group_mismatches(report_inputs) -> None:
    project, results, groups, rules = report_inputs
    result = results[0]

    with pytest.raises(ReportBuildError, match="rules package"):
        build_report_model(
            project,
            (result.model_copy(update={"rule_package_sha256": "f" * 64}),),
            groups,
            rules,
        )
    with pytest.raises(ReportBuildError, match="engine"):
        build_report_model(
            project,
            (result.model_copy(update={"calculation_engine_version": "stale"}),),
            groups,
            rules,
        )
    with pytest.raises(ReportBuildError, match="signature"):
        build_report_model(
            project,
            results,
            (groups[0].model_copy(update={"signature": "f" * 64}),),
            rules,
        )


def test_matrix_and_group_chapter_snapshot_all_audit_fields(report_model) -> None:
    row = report_model.matrix_rows[0]
    calculation = report_model.groups[0].calculations[0]

    assert row.pair_id == calculation.pair_id
    assert len(row.stresses) == 4
    assert row.frequency.provenance == "project_default"
    assert row.impulse.provenance == "project_default"
    assert row.insulation_type == "basic"
    assert row.insulation_type_provenance == "project_default"
    assert row.field_condition == "inhomogeneous"
    assert row.field_condition_provenance == "project_default"
    assert row.construction_type == "other"
    assert row.construction_type_provenance == "project_default"
    assert row.cti_or_material_group == "I"
    assert row.cti_or_material_group_provenance == "project_default"
    assert row.pollution_degree == 2
    assert row.pollution_degree_provenance == "project_default"
    assert row.altitude_m == 0
    assert row.altitude_provenance == "project_default"
    assert row.clearance_mm == calculation.clearance_mm
    assert row.creepage_mm == calculation.creepage_mm
    assert calculation.clearance_candidates
    assert calculation.creepage_candidates
    assert calculation.steps
    assert all(step.source_reference is not None for step in calculation.steps)
    assert {step.symbolic_latex.origin for step in calculation.steps} == {
        "approved_rules",
        "engine",
    }
    assert {step.substituted_latex.origin for step in calculation.steps} == {"engine"}


def test_report_formats_every_exact_source_locator(report_model) -> None:
    calculation = report_model.groups[0].calculations[0]
    step = calculation.steps[0].model_copy(
        update={
            "source_reference": SourceReference(
                standard="IEC 60664-1",
                edition="2020",
                clause="5.3.4",
                table="F.5",
                figure="F.1",
                row="150 V",
                column="PD 2",
                note="2",
            )
        }
    )
    changed_calculation = calculation.model_copy(
        update={"steps": (step, *calculation.steps[1:])}
    )
    changed_group = report_model.groups[0].model_copy(
        update={"calculations": (changed_calculation,)}
    )
    changed_model = report_model.model_copy(update={"groups": (changed_group,)})

    tex = render_latex(changed_model)

    assert (
        "IEC 60664-1:2020, 5.3.4, Table F.5, Figure F.1, Note 2, row 150 V, column PD 2"
        in tex
    )


def test_report_rejects_internally_mismatched_results_and_tampered_rules(
    report_inputs,
) -> None:
    project, results, groups, rules = report_inputs
    result = results[0]
    changed_result = result.model_copy(update={"clearance_mm": result.clearance_mm + 1})

    with pytest.raises(ReportBuildError, match="clearance result"):
        build_report_model(
            project,
            (changed_result,),
            (
                groups[0].model_copy(
                    update={"signature": calculation_signature(changed_result)}
                ),
            ),
            rules,
        )
    table = rules.tables[0]
    cell = table.cells[0]
    tampered_rules = rules.model_copy(
        update={
            "tables": (
                table.model_copy(
                    update={
                        "cells": (
                            cell.model_copy(update={"value": cell.value + 1}),
                            *table.cells[1:],
                        )
                    }
                ),
                *rules.tables[1:],
            )
        }
    )
    with pytest.raises(ReportBuildError, match="failed validation"):
        build_report_model(project, results, groups, tampered_rules)
