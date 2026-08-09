"""Public synthetic Slice C reference, archive, and evaluation integration."""

from __future__ import annotations

from decimal import Decimal

from insulation_coordination.domain.rules import (
    DecisionInput,
    DecisionOutput,
    DecisionRow,
    DecisionRule,
    DecisionValue,
    Matcher,
)
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.rules.evaluator import evaluate_piecewise_curve
from insulation_coordination.rules.validation import validate_rule_package
from tests.fixtures.synthetic_rules import synthetic_rule_package


def _result(package, code: str):
    return next(item for item in validate_rule_package(package).results if item.code == code)


def _referencing_package():
    package = synthetic_rule_package()
    curve = package.curves[0]
    source = package.decisions[0].source
    reference = DecisionRule(
        id="synthetic-slice-c-reference",
        inputs=(
            DecisionInput(
                name="synthetic_case",
                kind="categorical",
                allowed_values=("curve",),
            ),
        ),
        outputs=(DecisionOutput(name="target", kind="reference"),),
        rows=(
            DecisionRow(
                matchers=(
                    Matcher(input="synthetic_case", op="equals", values=("curve",)),
                ),
                values=(DecisionValue(name="target", reference=curve.id),),
                source=source,
            ),
        ),
        exhaustive=True,
        source=source,
    )
    return package.model_copy(
        update={
            "decisions": (*package.decisions, reference),
            "checksums": {},
            "package_sha256": None,
        }
    )


def test_curve_reference_resolves_round_trips_and_evaluates(tmp_path) -> None:
    package = _referencing_package()
    curve_reference = next(
        value.reference
        for decision in package.decisions
        for row in decision.rows
        for value in row.values
        if value.reference == package.curves[0].id
    )
    curve_by_id = {curve.id: curve for curve in package.curves}

    assert curve_by_id[curve_reference] is package.curves[0]
    assert _result(package, "SEMANTIC_REFERENCES_RESOLVE").passed is True

    path = tmp_path / "synthetic-slice-c.icrules"
    write_rule_package(path, package)
    reloaded = load_rule_package(path)
    assert reloaded.curves == package.curves
    variant = reloaded.curves[0].variants[0]
    result = evaluate_piecewise_curve(
        reloaded.curves[0], variant.selector, Decimal(27)
    )
    assert result.status == "matched"


def test_missing_or_ambiguous_semantic_reference_fails_exact_resolution() -> None:
    package = _referencing_package()
    decision = package.decisions[-1]
    dangling = decision.model_copy(
        update={
            "rows": (
                decision.rows[0].model_copy(
                    update={
                        "values": (
                            decision.rows[0].values[0].model_copy(
                                update={"reference": "synthetic-missing"}
                            ),
                        )
                    }
                ),
            )
        }
    )
    duplicate_formula = package.formulas[0].model_copy(
        update={"id": package.curves[0].id}
    )
    ambiguous = package.model_copy(
        update={"formulas": (*package.formulas, duplicate_formula)}
    )

    assert _result(
        package.model_copy(update={"decisions": (*package.decisions[:-1], dangling)}),
        "SEMANTIC_REFERENCES_RESOLVE",
    ).passed is False
    assert _result(ambiguous, "SEMANTIC_REFERENCES_RESOLVE").passed is False
