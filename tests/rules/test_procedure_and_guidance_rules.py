import pytest
from pydantic import ValidationError

from insulation_coordination.domain.rules import (
    GuidanceRule,
    ProcedureRule,
    ProcedureStep,
    SourceReference,
)

SOURCE = SourceReference(document_id="synthetic-source", standard="SYNTHETIC-1", edition="1", clause="9.1", table="T-26")


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
        source=SOURCE,
    )
    assert ProcedureRule.model_validate(rule.model_dump(mode="json")) == rule


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
