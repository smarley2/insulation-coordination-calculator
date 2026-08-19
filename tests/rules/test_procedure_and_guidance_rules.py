import pytest
from pydantic import ValidationError

from insulation_coordination.domain.rules import (
    GuidanceRule,
    PermittedAlternative,
    ProcedureRule,
    ProcedureStep,
    SourceReference,
)

SOURCE = SourceReference(
    document_id="synthetic-source", standard="SYNTHETIC-1", edition="1", clause="9.1", table="T-26"
)


def _step(order: int) -> ProcedureStep:
    return ProcedureStep(order=order, text=f"synthetic step {order}", source=SOURCE)


def test_procedure_round_trip_preserves_every_field() -> None:
    rule = ProcedureRule(
        id="synthetic-procedure",
        test_kind="synthetic-impulse",
        classifications=("type",),
        waveform="synthetic waveform",
        polarity="synthetic polarity",
        duration="synthetic duration",
        repetitions="synthetic repetitions",
        preparation_steps=(_step(1),),
        procedure_steps=(_step(1), _step(2)),
        acceptance_reference=SOURCE,
        applicability_rule_id="synthetic-decision",
        permitted_alternative=PermittedAlternative(
            instead_of_rule_id="synthetic-replaced-test",
            equivalent_measure="peak",
            equivalent_to_rule_id="synthetic-voltage-table",
            ramp="synthetic ramp allowance",
        ),
        source=SOURCE,
    )
    assert ProcedureRule.model_validate(rule.model_dump(mode="json")) == rule


def test_a_procedure_states_no_alternative_unless_the_source_permits_one() -> None:
    rule = ProcedureRule(
        id="synthetic-procedure",
        test_kind="synthetic-impulse",
        procedure_steps=(_step(1),),
        source=SOURCE,
    )
    assert rule.permitted_alternative is None


@pytest.mark.parametrize("field", ["instead_of_rule_id", "equivalent_to_rule_id"])
def test_a_procedure_cannot_be_a_permitted_alternative_to_itself(field: str) -> None:
    """A substitution names two rules. One rule naming itself states no substitution at all."""
    references = {
        "instead_of_rule_id": "synthetic-replaced-test",
        "equivalent_to_rule_id": "synthetic-voltage-table",
        field: "synthetic-procedure",
    }
    with pytest.raises(ValidationError, match="alternative to itself"):
        ProcedureRule(
            id="synthetic-procedure",
            test_kind="synthetic-impulse",
            procedure_steps=(_step(1),),
            permitted_alternative=PermittedAlternative(equivalent_measure="average", **references),
            source=SOURCE,
        )


def test_an_equivalence_measure_outside_the_declared_vocabulary_is_refused() -> None:
    with pytest.raises(ValidationError):
        PermittedAlternative(
            instead_of_rule_id="synthetic-replaced-test",
            equivalent_measure="rms",  # type: ignore[arg-type]
            equivalent_to_rule_id="synthetic-voltage-table",
        )


def test_procedure_steps_must_be_numbered_from_one_without_gaps() -> None:
    with pytest.raises(ValidationError, match="consecutive"):
        ProcedureRule(
            id="synthetic-procedure",
            test_kind="synthetic-impulse",
            procedure_steps=(_step(1), _step(3)),
            source=SOURCE,
        )


def test_procedure_without_any_step_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least one procedure step"):
        ProcedureRule(id="synthetic-procedure", test_kind="synthetic-impulse", source=SOURCE)


def test_guidance_round_trip_preserves_every_field() -> None:
    rule = GuidanceRule(
        id="synthetic-guidance",
        title="Synthetic guidance",
        summary="Synthetic summary.",
        warnings=("Synthetic warning.",),
        examples=("Synthetic example.",),
        source=SOURCE,
    )
    assert GuidanceRule.model_validate(rule.model_dump(mode="json")) == rule
