"""Typed projection for IEC 62477-1:2022 Tables 2 and 3.

The recipe supplies coordinates and semantic targets; all quantities remain extracted
source data. No curve or Table 7 value is copied into the resulting decisions.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Literal, NamedTuple, cast

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import (
    DecisionInput,
    DecisionOutput,
    DecisionRow,
    DecisionRule,
    DecisionValue,
    FaultTimeVoltageVariant,
    Identifier,
    Matcher,
    PiecewiseCurveRule,
    SourceReference,
)
from insulation_coordination.rules.importer.curves import RawFigure
from insulation_coordination.rules.importer.extract import (
    RawGrid,
    RawGridCell,
    SemanticProposal,
    apply_table_structure,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.identify import StandardIdentity
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.tables import (
    TABLE_2,
    TABLE_3,
)

OutcomeKind = Literal["numeric", "reference", "not_applicable"]
_REFERENCE_TARGET_KINDS = {
    ids.DVC_FAULT_TIME_VOLTAGE: "curve",
    f"{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.ac": "table",
    f"{ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE}.dc": "table",
}


class _Outcome(NamedTuple):
    row: int
    column: int
    kind: OutcomeKind
    value: Decimal | str | bool
    source: SourceReference


def _outcomes(grid: RawGrid) -> tuple[_Outcome, ...]:
    by_coordinate = {(cell.row, cell.column): cell for cell in grid.cells}
    outcomes: list[_Outcome] = []
    for row in range(2, grid.rows):
        for column in range(2, grid.columns):
            cell = by_coordinate[(row, column)]
            if any(
                value is None
                for value in (
                    cell.source.page,
                    cell.source.table,
                    cell.source.row,
                    cell.source.column,
                )
            ):
                raise ValueError("Table 2 outcome has incomplete typed provenance")
            if cell.reference_token is not None:
                expected_kind = _REFERENCE_TARGET_KINDS.get(
                    cell.reference_token.target_rule_id
                )
                if expected_kind != cell.reference_token.target_kind:
                    raise ValueError("Table 2 semantic reference has an invalid target kind")
                outcomes.append(
                    _Outcome(
                        row,
                        column,
                        "reference",
                        cell.reference_token.target_rule_id,
                        cell.reference_token.source,
                    )
                )
            elif cell.parse_status == "numeric" and cell.value is not None:
                outcomes.append(_Outcome(row, column, "numeric", cell.value, cell.source))
            elif cell.blank_semantics == "not_applicable":
                outcomes.append(_Outcome(row, column, "not_applicable", False, cell.source))
            else:
                raise ValueError(f"Table 2 has an unresolved outcome at {(row, column)}")
    return tuple(outcomes)


def _categorical_values(outcomes: Iterable[_Outcome], field: str) -> tuple[str, ...]:
    values = {
        {
            "dvc": f"dvc-row-{outcome.row + 1}",
            "operating_condition": f"condition-row-{outcome.row + 1}",
            "voltage_quantity": f"quantity-{(outcome.column - 2) // 2 + 1}",
        }[field]
        for outcome in outcomes
    }
    return tuple(sorted(values))


def _rule(grid: RawGrid, outcomes: tuple[_Outcome, ...], kind: OutcomeKind) -> DecisionRule:
    rule_id = {
        "numeric": ids.DVC_VOLTAGE_LIMITS,
        "reference": f"{ids.DVC_VOLTAGE_LIMITS}.references",
        "not_applicable": f"{ids.DVC_VOLTAGE_LIMITS}.not_applicable",
    }[kind]
    output = {
        "numeric": DecisionOutput(name="voltage_limit", kind="numeric", unit=grid.target_unit),
        "reference": DecisionOutput(name="voltage_limit", kind="reference"),
        "not_applicable": DecisionOutput(name="applicable", kind="boolean"),
    }[kind]
    rows = tuple(
        DecisionRow(
            matchers=(
                Matcher(input="dvc", op="equals", values=(f"dvc-row-{outcome.row + 1}",)),
                Matcher(
                    input="operating_condition",
                    op="equals",
                    values=(f"condition-row-{outcome.row + 1}",),
                ),
                Matcher(
                    input="voltage_quantity",
                    op="equals",
                    values=(f"quantity-{(outcome.column - 2) // 2 + 1}",),
                ),
                Matcher(input="unit", op="equals", values=(grid.target_unit,)),
                Matcher(
                    input="conditional_alternative",
                    op="equals",
                    boolean=bool((outcome.column - 2) % 2),
                ),
            ),
            values=(
                DecisionValue(
                    name=output.name,
                    numeric=cast(Decimal, outcome.value),
                    unit=grid.target_unit,
                )
                if kind == "numeric"
                else (
                    DecisionValue(name=output.name, reference=cast(str, outcome.value))
                    if kind == "reference"
                    else DecisionValue(name=output.name, boolean=False)
                ),
            ),
            source=outcome.source,
        )
        for outcome in outcomes
    )
    return DecisionRule(
        id=rule_id,
        inputs=(
            DecisionInput(
                name="dvc", kind="categorical", allowed_values=_categorical_values(outcomes, "dvc")
            ),
            DecisionInput(
                name="operating_condition",
                kind="categorical",
                allowed_values=_categorical_values(outcomes, "operating_condition"),
            ),
            DecisionInput(
                name="voltage_quantity",
                kind="categorical",
                allowed_values=_categorical_values(outcomes, "voltage_quantity"),
            ),
            DecisionInput(name="unit", kind="categorical", allowed_values=(grid.target_unit,)),
            DecisionInput(name="conditional_alternative", kind="boolean"),
        ),
        outputs=(output,),
        rows=rows,
        exhaustive=False,
        source=grid.source,
    )


def project_dvc_voltage_limits(
    grid: RawGrid,
    identity: StandardIdentity,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project a complete reviewed Table 2 grid into proposed typed decisions."""

    if grid.id != f"raw-{ids.DVC_VOLTAGE_LIMITS}":
        raise ValueError("Table 2 projection requires the DVC voltage-limit grid")
    if grid.source.standard != identity.standard or grid.source.edition != identity.edition:
        raise ValueError("Table 2 grid does not match its identified source")
    structured = apply_table_structure(grid, TABLE_2)
    outcomes = _outcomes(structured)
    rules = tuple(
        _rule(structured, selected, kind)
        for kind in ("numeric", "reference", "not_applicable")
        if (selected := tuple(item for item in outcomes if item.kind == kind))
    )
    artifact_sha256 = canonical_model_sha256(structured)
    proposals = tuple(
        SemanticProposal(
            semantic_id=rule.id,
            rule_kind="decision",
            state="proposed",
            rule_sha256=canonical_model_sha256(rule),
            source_artifact_sha256=artifact_sha256,
        )
        for rule in rules
    )
    return rules, proposals


class ProtectionOutcome(FrozenModel):
    """One reviewed Table 3 data cell as a typed protection outcome."""

    category: Identifier
    evidence_required: bool
    applicable: bool
    source: SourceReference


class _ProtectionCell(NamedTuple):
    row: int
    column: int
    token: bool
    source: SourceReference


#: How each ``ProtectionOutcome`` field is derived from one reviewed yes/no cell:
#: ``yes`` names the combinations (DVC row × protection condition) for which the
#: standard requires protective measures plus their verification evidence;
#: ``no`` names combinations where neither applies. Both fields therefore mirror
#: the reviewed token on purpose; the derivation is stated here rather than left
#: as silent duplication, and the projected rows keep it as ``field == met``
#: comparisons so a met/unmet mismatch flips both typed outcomes.
_PROTECTION_OUTCOME_DERIVATION = "reviewed-cell-token"


def _derive_protection_outcome_fields(token: bool) -> tuple[bool, bool]:
    """The explicit derivation named by ``_PROTECTION_OUTCOME_DERIVATION``.

    A reviewed ``yes`` cell means protective measures and their verification
    evidence are both required for that combination; ``no`` means neither
    applies. The two fields are derived independently here — not copied from one
    another — so a future standard revision that splits them changes exactly
    one place.
    """

    if _PROTECTION_OUTCOME_DERIVATION != "reviewed-cell-token":
        raise ValueError("unsupported Table 3 outcome derivation")
    return token, token


def _protection_cells(grid: RawGrid) -> tuple[_ProtectionCell, ...]:
    by_coordinate = {(cell.row, cell.column): cell for cell in grid.cells}
    cells: list[_ProtectionCell] = []
    data_coordinates = tuple(
        (row, column) for row in range(2, grid.rows) for column in range(2, grid.columns)
    )
    for row, column in data_coordinates:
        cell = by_coordinate.get((row, column))
        if cell is None or cell.role != "data":
            raise ValueError("Table 3 has incomplete Cartesian coverage")
        if any(
            value is None
            for value in (
                cell.source.page,
                cell.source.table,
                cell.source.row,
                cell.source.column,
            )
        ):
            raise ValueError("Table 3 outcome has incomplete typed provenance")
        token = _protection_token(cell)
        if cell.value is not None or token is None:
            raise ValueError(f"Table 3 has an unknown boolean token at {(row, column)}")
        cells.append(_ProtectionCell(row, column, token, cell.source))
    return tuple(cells)


def _protection_token(cell: RawGridCell) -> bool | None:
    grammar = TABLE_3.token_grammar
    if grammar is None or grammar.target != "boolean":
        raise ValueError("Table 3 requires a boolean token grammar")
    return grammar.resolve(cell.raw_text)


def _protection_rule(
    grid: RawGrid,
    cells: tuple[_ProtectionCell, ...],
    field: Literal["evidence_required", "applicable"],
) -> DecisionRule:
    rule_id = (
        ids.DVC_PROTECTION_MATRIX
        if field == "evidence_required"
        else f"{ids.DVC_PROTECTION_MATRIX}.applicable"
    )
    categories = tuple(f"category-row-{row - 1}" for row in range(2, grid.rows))
    conditions = tuple(f"condition-column-{column - 1}" for column in range(2, grid.columns))
    outcomes = tuple(
        ProtectionOutcome(
            category=categories[cell.row - 2],
            evidence_required=(derived := _derive_protection_outcome_fields(cell.token))[0],
            applicable=derived[1],
            source=cell.source,
        )
        for cell in cells
    )
    return DecisionRule(
        id=rule_id,
        inputs=(
            DecisionInput(
                name="dvc",
                kind="categorical",
                allowed_values=categories,
            ),
            DecisionInput(
                name="protection_condition",
                kind="categorical",
                allowed_values=conditions,
            ),
            DecisionInput(name="protection_condition_met", kind="boolean"),
        ),
        outputs=(DecisionOutput(name=field, kind="boolean"),),
        rows=tuple(
            DecisionRow(
                matchers=(
                    Matcher(
                        input="dvc",
                        op="equals",
                        values=(outcome.category,),
                    ),
                    Matcher(
                        input="protection_condition",
                        op="equals",
                        values=(conditions[cell.column - 2],),
                    ),
                    Matcher(
                        input="protection_condition_met",
                        op="equals",
                        boolean=met,
                    ),
                ),
                values=(
                    DecisionValue(
                        name=field,
                        boolean=getattr(outcome, field) == met,
                    ),
                ),
                source=outcome.source,
            )
            for cell, outcome in zip(cells, outcomes, strict=True)
            for met in (False, True)
        ),
        exhaustive=True,
        source=grid.source,
    )


def project_dvc_protection_matrix(
    grid: RawGrid,
    identity: StandardIdentity,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project a complete reviewed Table 3 grid into proposed typed decisions."""

    if grid.id != f"raw-{ids.DVC_PROTECTION_MATRIX}":
        raise ValueError("Table 3 projection requires the DVC protection matrix grid")
    if grid.source.standard != identity.standard or grid.source.edition != identity.edition:
        raise ValueError("Table 3 grid does not match its identified source")
    structured = apply_table_structure(grid, TABLE_3)
    expected = {
        (row, column)
        for row in range(2, structured.rows)
        for column in range(2, structured.columns)
    }
    present = {
        (cell.row, cell.column) for cell in structured.cells if cell.role == "data"
    }
    if present != expected:
        raise ValueError("Table 3 has incomplete Cartesian coverage")
    cells = _protection_cells(structured)
    rules = tuple(
        _protection_rule(structured, cells, field) for field in ("evidence_required", "applicable")
    )
    artifact_sha256 = canonical_model_sha256(structured)
    proposals = tuple(
        SemanticProposal(
            semantic_id=rule.id,
            rule_kind="decision",
            state="proposed",
            rule_sha256=canonical_model_sha256(rule),
            source_artifact_sha256=artifact_sha256,
        )
        for rule in rules
    )
    return rules, proposals


__all__ = [
    "ProtectionOutcome",
    "project_dvc_protection_matrix",
    "project_dvc_voltage_limits",
    "project_fault_time_voltage",
]


def project_fault_time_voltage(
    figures: tuple[RawFigure, ...],
    figure5_variants: tuple[FaultTimeVoltageVariant, ...],
    figure6_variants: tuple[FaultTimeVoltageVariant, ...],
    figure7_variants: tuple[FaultTimeVoltageVariant, ...],
    identity: StandardIdentity,
) -> tuple[PiecewiseCurveRule, tuple[SemanticProposal, ...]]:
    """Associate reviewed Figure 5–7 variants into one proposed curve rule.

    Figure order is fixed (5, 6, 7) and each figure must be present exactly once;
    every variant keeps its exact four-dimension selector. The aggregate proposal's
    artifact hash covers the ordered figure artifact digests, so any figure change
    resets the review.
    """

    if len(figures) != 3 or any(
        not isinstance(figure, RawFigure) for figure in figures
    ):
        raise ValueError("Figure 5, 6, and 7 artifacts are required exactly once")
    pages = tuple(figure.source.page for figure in figures)
    if pages != (54, 55, 56):
        raise ValueError(f"Figure pages must be 54, 55, 56 in order, got {pages}")
    member_groups = (figure5_variants, figure6_variants, figure7_variants)
    if any(len(members) != 1 for members in member_groups):
        raise ValueError("Figure 5, 6, and 7 each require exactly one curve variant")
    variants = (*figure5_variants, *figure6_variants, *figure7_variants)
    selectors = tuple(variant.selector for variant in variants)
    if len(set(selectors)) != len(selectors):
        raise ValueError("curve variant selectors must be exact and unique")
    expected_roles = (
        ("accessible_circuit", "ac_rms", True),
        ("accessible_circuit", "dc", True),
        ("conductive_accessible_part", "ac_peak", False),
    )
    for figure_number, variant, (subject, basis, contextual) in zip(
        (5, 6, 7), variants, expected_roles, strict=True
    ):
        selector = variant.selector
        if selector.subject != subject or selector.voltage_basis != basis:
            raise ValueError(f"Figure {figure_number} variant has the wrong semantic role")
        has_context = (
            selector.dvc_context is not None
            and selector.environment_context is not None
        )
        if has_context != contextual:
            raise ValueError(f"Figure {figure_number} variant has the wrong context dimensions")
    for figure_number, figure, members in zip(
        (5, 6, 7),
        figures,
        (figure5_variants, figure6_variants, figure7_variants),
        strict=True,
    ):
        for variant in members:
            if (
                variant.reviewed_artifact_sha256 != figure.artifact_sha256
                or variant.source.document_id != figure.source.document_id
                or variant.source.page != figure.source.page
                or variant.source.figure != figure.source.figure
            ):
                raise ValueError(
                    f"Figure {figure_number} variant is not linked to its source artifact"
                )
    for figure in figures:
        if figure.source.standard != identity.standard or figure.source.edition != identity.edition:
            raise ValueError("figure artifact does not match its identified source")
    rule = PiecewiseCurveRule(
        id=ids.DVC_FAULT_TIME_VOLTAGE,
        variants=variants,
        source=figures[0].source.model_copy(update={"figure": "5-7"}),
    )
    from insulation_coordination.rules.importer.review import _aggregate_artifact_pairs

    aggregate = _aggregate_artifact_pairs(
        tuple((variant.id, variant.reviewed_artifact_sha256) for variant in variants)
    )
    proposal = SemanticProposal(
        semantic_id=rule.id,
        rule_kind="curve",
        state="proposed",
        rule_sha256=canonical_model_sha256(rule),
        source_artifact_sha256=aggregate,
    )
    return rule, (proposal,)
