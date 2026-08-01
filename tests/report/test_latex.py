from uuid import UUID

import pytest
from pydantic import ValidationError

from insulation_coordination.calculation.engine import (
    CalculationWarning,
    VerificationRequirement,
    calculate_pair,
)
from insulation_coordination.calculation.grouping import calculation_signature, group_results
from insulation_coordination.domain.project import RulePackageReference
from insulation_coordination.domain.rules import Round, SourceReference
from insulation_coordination.project.resolver import resolve_effective_case
from insulation_coordination.report.latex import render_latex
from insulation_coordination.report.model import (
    ReportBuildError,
    ReportStep,
    TrustedFormulaLatex,
    build_report_model,
)
from insulation_coordination.rules.archive import load_rule_package, write_rule_package


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


def test_report_defensively_rejects_unchecked_duplicate_project_pair_ids(
    report_inputs,
) -> None:
    project, results, groups, rules = report_inputs
    pair = project.pairs[0]
    unchecked = project.model_copy(update={"pairs": (pair, pair.model_copy())})

    with pytest.raises(ReportBuildError, match="duplicate pair ID in project"):
        build_report_model(unchecked, results, groups, rules)


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
    assert len(calculation.stresses) == 4
    assert {stress.provenance for stress in calculation.stresses} == {"pair_input"}
    assert calculation.steps
    assert all(step.source_reference is not None for step in calculation.steps)
    assert {step.symbolic_latex.origin for step in calculation.steps} == {
        "approved_rules",
        "engine",
    }
    assert {step.substituted_latex.origin for step in calculation.steps} == {"engine"}


def test_group_chapter_renders_all_voltage_states_and_pair_linked_advisories(
    report_model,
) -> None:
    calculation = report_model.groups[0].calculations[0]
    changed_calculation = calculation.model_copy(
        update={
            "warnings": (
                CalculationWarning(code="PAIR_WARNING", message="Synthetic pair warning."),
            ),
            "verification_requirements": (
                VerificationRequirement(
                    code="PAIR_CHECK",
                    message="Synthetic pair verification.",
                ),
            ),
        }
    )
    changed_group = report_model.groups[0].model_copy(
        update={"calculations": (changed_calculation,)}
    )
    changed_model = report_model.model_copy(update={"groups": (changed_group,)})

    grouped_tex = render_latex(changed_model).split(r"\section{Grouped Calculations}", 1)[1]

    assert r"\paragraph{Effective voltage stresses.}" in grouped_tex
    assert "long-term RMS" in grouped_tex
    assert "steady-state peak" in grouped_tex
    assert "recurring peak" in grouped_tex
    assert "temporary overvoltage peak" in grouped_tex
    assert "not\\_applicable" in grouped_tex
    assert "No recurring peak." in grouped_tex
    assert "pair\\_input" in grouped_tex
    assert f"Affected pair ID: {calculation.pair_id}" in grouped_tex
    assert "PAIR\\_WARNING" in grouped_tex
    assert "Synthetic pair warning." in grouped_tex
    assert "PAIR\\_CHECK" in grouped_tex
    assert "Synthetic pair verification." in grouped_tex


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
    changed_calculation = calculation.model_copy(update={"steps": (step, *calculation.steps[1:])})
    changed_group = report_model.groups[0].model_copy(
        update={"calculations": (changed_calculation,)}
    )
    changed_model = report_model.model_copy(update={"groups": (changed_group,)})

    tex = render_latex(changed_model)

    assert "IEC 60664-1:2020, 5.3.4, Table F.5, Figure F.1, Note 2, row 150 V, column PD 2" in tex


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
            (groups[0].model_copy(update={"signature": calculation_signature(changed_result)}),),
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


@pytest.mark.parametrize("tamper", ["candidate", "step", "omitted_step"])
def test_report_recomputes_and_rejects_complete_but_tampered_trace(
    report_inputs,
    tamper: str,
) -> None:
    project, results, groups, rules = report_inputs
    result = results[0]
    trace = result.trace
    if tamper == "candidate":
        non_governing_index = next(
            index
            for index, candidate in enumerate(trace.clearance_candidates)
            if candidate.candidate_id != trace.governing_clearance_candidate_id
        )
        candidates = list(trace.clearance_candidates)
        candidates[non_governing_index] = candidates[non_governing_index].model_copy(
            update={"reason": "tampered but internally non-governing"}
        )
        changed_trace = trace.model_copy(update={"clearance_candidates": tuple(candidates)})
    elif tamper == "step":
        changed_step = trace.steps[0].model_copy(update={"reason": "tampered trace step"})
        changed_trace = trace.model_copy(update={"steps": (changed_step, *trace.steps[1:])})
    else:
        changed_trace = trace.model_copy(update={"steps": trace.steps[:-1]})
    changed_result = result.model_copy(update={"trace": changed_trace})
    changed_group = groups[0].model_copy(
        update={"signature": calculation_signature(changed_result)}
    )

    with pytest.raises(ReportBuildError, match="authoritative recalculation"):
        build_report_model(project, (changed_result,), (changed_group,), rules)


@pytest.mark.parametrize("origin", ["approved_rules", "engine"])
@pytest.mark.parametrize("command", ["input", "include", "write", "catcode"])
def test_trusted_formula_type_rejects_dangerous_commands(
    origin: str,
    command: str,
) -> None:
    with pytest.raises(ValidationError, match="unsafe math LaTeX"):
        TrustedFormulaLatex(latex=rf"x + \{command}{{payload}}", origin=origin)


@pytest.mark.parametrize("latex", ["x % comment", "x\n+y", r"x + \unknown{y}"])
def test_trusted_formula_type_rejects_comments_controls_and_unknown_commands(
    latex: str,
) -> None:
    with pytest.raises(ValidationError, match="unsafe math LaTeX"):
        TrustedFormulaLatex(latex=latex, origin="engine")


def test_trusted_formula_type_allows_commands_used_by_approved_rules() -> None:
    latex = r"r/d\geq k_{synthetic}"

    formula = TrustedFormulaLatex(latex=latex, origin="approved_rules")

    assert formula.latex == latex


@pytest.mark.parametrize("field", ["symbolic_latex", "substituted_latex"])
@pytest.mark.parametrize(
    "latex",
    [
        "^^5cinput{payload}",
        "^^5Cinput{payload}",
        "^^5c^^69nput{payload}",
        "^^5Cin^^70ut{payload}",
    ],
)
def test_report_step_rejects_tex_character_code_command_construction(
    report_model,
    field: str,
    latex: str,
) -> None:
    step_data = report_model.groups[0].calculations[0].steps[0].model_dump(mode="python")
    step_data[field] = {
        "latex": latex,
        "origin": "approved_rules" if field == "symbolic_latex" else "engine",
    }

    with pytest.raises(ValidationError, match="unsafe math LaTeX"):
        ReportStep.model_validate(step_data)


def test_report_renders_single_caret_superscripts_and_allowed_commands(report_model) -> None:
    calculation = report_model.groups[0].calculations[0]
    step = calculation.steps[0].model_copy(
        update={
            "symbolic_latex": TrustedFormulaLatex(
                latex=r"x^{2}\geq y",
                origin="approved_rules",
            ),
            "substituted_latex": TrustedFormulaLatex(
                latex=r"2^{2}\,\mathrm{V}",
                origin="engine",
            ),
        }
    )
    changed_calculation = calculation.model_copy(update={"steps": (step, *calculation.steps[1:])})
    changed_group = report_model.groups[0].model_copy(
        update={"calculations": (changed_calculation,)}
    )

    tex = render_latex(report_model.model_copy(update={"groups": (changed_group,)}))

    assert r"x^{2}\geq y" in tex
    assert r"2^{2}\,\mathrm{V}" in tex


def test_report_rejects_dangerous_formula_from_otherwise_valid_approved_package(
    report_inputs,
    tmp_path,
) -> None:
    project, _, _, rules = report_inputs
    unsafe_source = rules.model_copy(
        update={
            "formulas": tuple(
                formula.model_copy(
                    update={
                        "expression": Round(
                            value=formula.expression,
                            places=2,
                            mode="ROUND_HALF_UP",
                        ),
                        "latex": r"d = \input{payload}",
                    }
                )
                for formula in rules.formulas
            ),
            "checksums": {},
            "package_sha256": None,
        }
    )
    rules_path = tmp_path / "unsafe-formula.icrules"
    write_rule_package(rules_path, unsafe_source)
    unsafe_rules = load_rule_package(rules_path)
    assert unsafe_rules.package_sha256 is not None
    unsafe_project = project.model_copy(
        update={
            "required_rules": RulePackageReference(
                package_id=str(unsafe_rules.manifest.package_id),
                version=unsafe_rules.manifest.version,
                sha256=unsafe_rules.package_sha256,
            )
        }
    )
    unsafe_result = calculate_pair(
        resolve_effective_case(unsafe_project.defaults, unsafe_project.pairs[0]),
        unsafe_rules,
    )

    with pytest.raises(ReportBuildError, match="unsafe math LaTeX"):
        build_report_model(
            unsafe_project,
            (unsafe_result,),
            group_results((unsafe_result,), ()),
            unsafe_rules,
        )
