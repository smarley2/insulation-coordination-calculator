"""IEC 62477-1:2022 clause recipes and DVC fault-applicability projection.

The recipe declares page/bbox/shape locators only. Reviewed neutral token roles map
to applicability decisions; any structure outside the reviewed roles blocks with
``AMBIGUOUS_CLAUSE_STRUCTURE`` instead of guessing.
"""

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
from insulation_coordination.rules.importer.clauses import RawClauseFragment
from insulation_coordination.rules.importer.extract import (
    SemanticProposal,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.identify import (
    ClauseAuditSpec,
    StandardIdentity,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids

CLAUSES: tuple[ClauseAuditSpec, ...] = (
    ClauseAuditSpec(
        semantic_id=ids.DVC_FAULT_APPLICABILITY,
        clause="4.4.2",
        page_number=44,
        expected_bbox=(70.9, 664.0, 524.4, 740.0),
        expected_root_kind="bullets",
        output_kind="decision",
    ),
)

#: Reviewed token-role contract for the DVC fault-applicability fragment. The
#: fragment holds exactly one duration bound (operator, quantity, unit) shared by
#: every bullet, one condition role per bullet, and exactly one curve reference
#: role naming the fault-time-voltage curve rule. Anything else blocks.
_CONTRACT_QUANTITY_COUNT = 1
_CONTRACT_UNIT = "s"
_CONTRACT_OPERATORS = frozenset({"lte", "lt", "gte", "gt"})
_CONTRACT_REFERENCE = ids.DVC_FAULT_TIME_VOLTAGE


class ClauseStructureError(ValueError):
    """A reviewed clause fragment falls outside the declared token contract."""


def _fail(message: str) -> None:
    raise ClauseStructureError(f"AMBIGUOUS_CLAUSE_STRUCTURE: {message}")


def project_dvc_fault_applicability(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project a reviewed DVC fault-applicability fragment into a typed decision."""

    if fragment.id != f"raw-{ids.DVC_FAULT_APPLICABILITY}":
        raise ValueError("DVC fault applicability projection requires its own fragment")
    if fragment.source.standard != identity.standard or fragment.source.edition != identity.edition:
        raise ValueError("DVC fault applicability fragment does not match its identified source")

    conditions = tuple(
        str(token.normalized) for token in fragment.tokens if token.kind == "condition"
    )
    operators = tuple(
        token.normalized for token in fragment.tokens if token.kind == "operator"
    )
    quantities = tuple(
        token.normalized for token in fragment.tokens if token.kind == "quantity"
    )
    units = tuple(token.normalized for token in fragment.tokens if token.kind == "unit")
    references = tuple(
        token.normalized for token in fragment.tokens if token.kind == "reference"
    )
    if len(conditions) != len(fragment.nodes) or len(set(conditions)) != len(conditions):
        _fail("expected exactly one distinct condition token per clause node")
    if len(operators) != 1 or str(operators[0]) not in _CONTRACT_OPERATORS:
        _fail("expected exactly one reviewed duration operator")
    if len(quantities) != _CONTRACT_QUANTITY_COUNT or not isinstance(
        quantities[0], Decimal
    ):
        _fail("expected exactly one reviewed duration quantity")
    quantity_node = next(
        token.source.row
        for token in fragment.tokens
        if token.kind == "quantity"
    )
    source_node = next(
        node for node in fragment.nodes if node.source.row == quantity_node
    )
    if str(quantities[0]) not in source_node.raw_text.replace(",", "."):
        _fail("duration quantity does not match its reviewed source text")
    if len(units) != 1 or str(units[0]) != _CONTRACT_UNIT:
        _fail("expected exactly one reviewed duration unit")
    if len(references) != 1 or str(references[0]) != _CONTRACT_REFERENCE:
        _fail("expected exactly one reviewed curve reference")

    duration = quantities[0]
    assert isinstance(duration, Decimal)
    operator = str(operators[0])
    inclusive = operator in ("lte", "gte")
    lower_bound = operator in ("lte", "lt")
    dvc_values = tuple(f"dvc-row-{row}" for row in range(1, 8))
    rule = DecisionRule(
        id=ids.DVC_FAULT_APPLICABILITY,
        inputs=(
            DecisionInput(
                name="dvc",
                kind="categorical",
                allowed_values=dvc_values,
            ),
            DecisionInput(
                name="supply_condition",
                kind="categorical",
                allowed_values=conditions,
            ),
            DecisionInput(name="fault_duration_s", kind="numeric", unit="s"),
        ),
        outputs=(
            DecisionOutput(name="curve_applicability", kind="boolean"),
            DecisionOutput(name="required_curve", kind="reference"),
        ),
        rows=tuple(
            DecisionRow(
                matchers=(
                    Matcher(input="dvc", op="equals", values=(dvc,)),
                    Matcher(input="supply_condition", op="equals", values=(condition,)),
                    Matcher(
                        input="fault_duration_s",
                        op="range",
                        minimum=None if lower_bound else duration,
                        maximum=duration if lower_bound else None,
                        minimum_inclusive=inclusive,
                        maximum_inclusive=inclusive,
                    ),
                ),
                values=(
                    DecisionValue(name="curve_applicability", boolean=True),
                    DecisionValue(
                        name="required_curve", reference=ids.DVC_FAULT_TIME_VOLTAGE
                    ),
                ),
                source=fragment.source,
            )
            for dvc in dvc_values
            for condition in conditions
        ),
        exhaustive=False,
        source=fragment.source,
    )
    proposal = SemanticProposal(
        semantic_id=rule.id,
        rule_kind="decision",
        state="proposed",
        rule_sha256=canonical_model_sha256(rule),
        source_artifact_sha256=canonical_model_sha256(fragment),
    )
    return (rule,), (proposal,)


__all__ = ["CLAUSES", "ClauseStructureError", "project_dvc_fault_applicability"]
