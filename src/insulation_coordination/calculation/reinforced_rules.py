"""Resolves the IEC 62477-1:2022 reinforced treatment the spacing engines apply.

This is the one seam between a rule package and the stronger insulation's dimensioning. It
holds no normative content of its own: no factor, no level, no series, no threshold. What it
holds is the *shape* the treatment rule must have for this application to ask its question -
the input names it supplies, the output names it reads, the axis a step moves along - the two
generic algorithms that carry the answer out (:func:`multiply_stress` and
:func:`next_preferred_level`), and the refusal that follows when a package cannot answer.

Nothing here falls back. A package that is absent, unapproved, incompatible, missing a route,
or carrying a route shaped differently from the one this application resolves produces a
:class:`ReinforcedRuleBlock` naming the reason, and :func:`read_reinforced_rules` raises with
the complete list. Every block is collected before raising, so a reviewer fixing an
installation sees everything that is wrong with it at once. A treated distance that came from
a constant would look exactly like one that came from the standard, which is the whole reason
there is no constant to reach for instead.

**Two routes, one question.** Both routes answer "given an insulation class and the quantity
being treated, how is the design dimensioned", and both answer it in one of two modes. The
clearance route additionally states ``preferred_level_axis``, a reference to the requirement
whose row axis a step moves along; the creepage route deliberately states none, because a
reference resolves to exactly one rule and its requirements are two routes. So the axis is
never named here - it is followed from the rule, and the coordinates are resolved off the
referenced table at read time so that a broken reference is a package block rather than a
surprise mid-calculation.

**No edition gate**, unlike ``supply_rules`` and ``verification_rules``. The route identifiers
themselves name the standard and its edition, and only that edition's projector emits them, so
an edition check here would restate what the identifier already fixes - at the cost of forcing
every synthetic fixture that exercises the spacing engines to claim an IEC identity it has no
business claiming.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from insulation_coordination.calculation.clearance import CalculationError
from insulation_coordination.domain.frozen_model import FrozenModel
from insulation_coordination.domain.rules import DecisionRule, RulePackage, SourceReference
from insulation_coordination.domain.trace import Quantity, TraceStep
from insulation_coordination.rules.evaluator import evaluate_decision
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids

#: The route stating how a clearance is dimensioned for the stronger insulation.
CLEARANCE_ROUTE = ids.CLEARANCE_REINFORCED_TREATMENT
#: The route stating the same for a creepage distance.
CREEPAGE_ROUTE = ids.CREEPAGE_REINFORCED_TREATMENT

#: The identifiers this adapter resolves.
READ_SEMANTIC_IDS: frozenset[str] = frozenset({CLEARANCE_ROUTE, CREEPAGE_ROUTE})

#: What the treatment does with the quantity it is asked about. ``multiply`` scales it by the
#: stated factor; ``next_level_in_requirement_axis`` moves the design one coordinate up the row
#: axis of the requirement the treatment is stated against, and scales nothing.
MULTIPLY = "multiply"
NEXT_LEVEL_IN_REQUIREMENT_AXIS = "next_level_in_requirement_axis"

#: The question each route is resolved by. Inputs are compared for equality because the
#: evaluator answers ``input_required`` for any declared input a caller omits - a route
#: declaring one more input than this application knows about could not be asked anything at
#: all. Outputs are compared for containment: an output nothing here reads is harmless.
_INPUTS = frozenset({"insulation_class", "treated_quantity"})
_OUTPUTS = frozenset({"treatment_mode", "treatment_multiplier"})

#: The output naming the requirement a step moves along, stated by the clearance route alone.
_AXIS_OUTPUT = "preferred_level_axis"

#: The row axis of the referenced requirement, and the unit its coordinates and this
#: application's impulse stresses share. Structural, not a value.
_LEVEL_AXIS_ID = "impulse_withstand_voltage_v"
_VOLTAGE_UNIT = "V"


class ReinforcedRuleBlockCode(StrEnum):
    """Why the reinforced treatment cannot be applied. Typed, so a caller reports it whole."""

    NO_PACKAGE = "no_package"
    PACKAGE_NOT_APPROVED = "package_not_approved"
    PACKAGE_NOT_COMPATIBLE = "package_not_compatible"
    RULE_MISSING = "rule_missing"
    UNEXPECTED_SHAPE = "unexpected_shape"
    #: The route carries no reviewed statement for this insulation class and quantity. Not the
    #: same as a statement that nothing is done: an unreached row answers nothing at all.
    TREATMENT_NOT_STATED = "treatment_not_stated"
    #: A step was asked of a value that is not a coordinate of the referenced axis, so there is
    #: no "next" coordinate to move to. This is the case that used to fall through silently to
    #: a hard-coded factor.
    VALUE_OFF_AXIS = "value_off_axis"
    #: A step was asked of the highest coordinate the referenced axis carries.
    NO_HIGHER_LEVEL = "no_higher_level"


class ReinforcedRuleBlock(FrozenModel):
    """One reason the reinforced treatment cannot be applied against the active package."""

    code: ReinforcedRuleBlockCode
    message: str
    semantic_rule_id: str | None = None


class ReinforcedTreatmentUnavailable(CalculationError):
    """The active package cannot state how the stronger insulation is dimensioned.

    Carries every block rather than the first, because an installation is fixed by seeing the
    whole list. A :class:`~insulation_coordination.calculation.clearance.CalculationError`, so
    the report and the UI treat it exactly as they already treat an unusable rule package.
    """

    def __init__(self, blocks: tuple[ReinforcedRuleBlock, ...]) -> None:
        self.blocks = blocks
        detail = "; ".join(f"{block.code.value}: {block.message}" for block in blocks)
        super().__init__(f"reinforced treatment unavailable: {detail}")

    @property
    def codes(self) -> tuple[ReinforcedRuleBlockCode, ...]:
        return tuple(block.code for block in self.blocks)


class ReinforcedTreatment(FrozenModel):
    """What one route states for one insulation class and one treated quantity."""

    rule_id: str
    mode: str
    multiplier: Decimal
    #: The coordinates a step moves along, empty unless the mode is a step.
    levels: tuple[Decimal, ...] = ()
    #: The requirement the step's axis was read from, for the trace.
    level_axis_rule_id: str | None = None
    source: SourceReference | None = None


class ReinforcedRuleSet(FrozenModel):
    """Both reinforced treatment routes, resolved from one approved package.

    ``level_axes`` holds the coordinates of every requirement the clearance route defers to,
    read off the referenced table's row axis at resolution time and keyed by the referenced
    rule id. Resolving them here rather than at treatment time is what makes a reference to a
    rule the package does not carry a block a reviewer sees at once.
    """

    clearance: DecisionRule
    creepage: DecisionRule
    level_axes: dict[str, tuple[Decimal, ...]]

    def rule(self, route: str) -> DecisionRule:
        return self.clearance if route == CLEARANCE_ROUTE else self.creepage

    def treatment(
        self,
        route: str,
        *,
        insulation_class: str,
        treated_quantity: str,
    ) -> ReinforcedTreatment:
        """What ``route`` states for this class and quantity, or a raised block saying not."""

        rule = self.rule(route)
        result = evaluate_decision(
            rule,
            {"insulation_class": insulation_class, "treated_quantity": treated_quantity},
        )
        if result.status != "matched":
            raise ReinforcedTreatmentUnavailable(
                (
                    ReinforcedRuleBlock(
                        code=ReinforcedRuleBlockCode.TREATMENT_NOT_STATED,
                        semantic_rule_id=route,
                        message=(
                            f"The active package's {route} states no treatment for "
                            f"{insulation_class} insulation and a {treated_quantity}."
                        ),
                    ),
                )
            )
        values = {value.name: value for value in result.values}
        mode = values["treatment_mode"].categorical
        multiplier = values["treatment_multiplier"].numeric
        axis_rule_id = values[_AXIS_OUTPUT].reference if _AXIS_OUTPUT in values else None
        assert mode is not None and multiplier is not None  # the shape gate checked both
        return ReinforcedTreatment(
            rule_id=route,
            mode=mode,
            multiplier=multiplier,
            levels=self.level_axes.get(axis_rule_id or "", ()),
            level_axis_rule_id=axis_rule_id,
            source=result.source,
        )


def multiply_stress(value: Decimal, multiplier: Decimal) -> Decimal:
    """Scale one quantity by the factor a reviewed statement carries. The whole algorithm."""

    return value * multiplier


def next_preferred_level(levels: tuple[Decimal, ...], value: Decimal) -> Decimal:
    """The coordinate above ``value`` on ``levels``, or a raised block saying there is none.

    Both refusals were behaviours the removed constants had and neither said so: a value at the
    top of the series raised a range error the caller downgraded to a warning, and a value that
    was not on the series at all fell through to the multiplying branch. Both are now this
    adapter's typed block.
    """

    ordered = tuple(sorted(levels))
    if value not in ordered:
        raise ReinforcedTreatmentUnavailable(
            (
                ReinforcedRuleBlock(
                    code=ReinforcedRuleBlockCode.VALUE_OFF_AXIS,
                    message=(
                        f"{value} {_VOLTAGE_UNIT} is not a coordinate of the requirement axis "
                        "the reinforced treatment steps along, so it has no next level."
                    ),
                ),
            )
        )
    index = ordered.index(value) + 1
    if index >= len(ordered):
        raise ReinforcedTreatmentUnavailable(
            (
                ReinforcedRuleBlock(
                    code=ReinforcedRuleBlockCode.NO_HIGHER_LEVEL,
                    message=(
                        f"{value} {_VOLTAGE_UNIT} is the highest coordinate of the requirement "
                        "axis the reinforced treatment steps along, so no step remains."
                    ),
                ),
            )
        )
    return ordered[index]


def apply_reinforced_treatment(
    value: Decimal,
    *,
    unit: str,
    route: str,
    insulation_class: str,
    treated_quantity: str,
    rules: ReinforcedRuleSet,
    source: SourceReference | None = None,
    operation: str,
) -> tuple[Decimal, TraceStep]:
    """Dimension one quantity for the stronger insulation, and say how it was done.

    The wording of the step is this application's own account of what it did, carrying the
    identifier of the rule that decided it; nothing of the source's own procedure is restated.
    """

    treatment = rules.treatment(
        route, insulation_class=insulation_class, treated_quantity=treated_quantity
    )
    if treatment.mode == NEXT_LEVEL_IN_REQUIREMENT_AXIS:
        treated = next_preferred_level(treatment.levels, value)
        symbolic = r"X_{treated}=\mathrm{next}(X)"
        substituted = f"{value} {unit} = {treated} {unit}"
        reason = (
            f"{insulation_class} insulation is dimensioned one coordinate further along the "
            f"axis of {treatment.level_axis_rule_id}, as {treatment.rule_id} directs"
        )
    else:
        treated = multiply_stress(value, treatment.multiplier)
        symbolic = r"X_{treated}=k \times X"
        substituted = f"{value} {unit} = {treated} {unit}"
        reason = (
            f"{insulation_class} insulation scales the {treated_quantity} by the factor "
            f"{treatment.rule_id} states"
        )
    step = TraceStep(
        semantic_rule_id=treatment.rule_id,
        operation=operation,
        symbolic=symbolic,
        substituted=substituted,
        inputs=(Quantity(value=value, unit=unit),),
        source_reference=treatment.source or source,
        output=Quantity(value=treated, unit=unit),
        unrounded_value=treated,
        reason=reason,
    )
    return treated, step


def reinforced_rule_blocks(package: RulePackage | None) -> tuple[ReinforcedRuleBlock, ...]:
    """Every reason ``package`` cannot state the reinforced treatment.

    Empty means :func:`read_reinforced_rules` will succeed. For a caller that renders the
    reasons rather than aborting on them.
    """

    return _resolve(package)[1]


def read_reinforced_rules(package: RulePackage | None) -> ReinforcedRuleSet:
    """The treatment routes resolved from ``package``, or a raised list of every reason not.

    ``None`` is the state where no package is loaded at all, and blocks exactly like a package
    that is loaded but unapproved: neither may be dimensioned from.
    """

    resolved, blocks = _resolve(package)
    if resolved is None:
        raise ReinforcedTreatmentUnavailable(blocks)
    return resolved


def _resolve(
    package: RulePackage | None,
) -> tuple[ReinforcedRuleSet | None, tuple[ReinforcedRuleBlock, ...]]:
    if package is None:
        return None, (
            ReinforcedRuleBlock(
                code=ReinforcedRuleBlockCode.NO_PACKAGE,
                message="No rule package is loaded.",
            ),
        )
    reader = _PackageReader(package)
    trust = reader.trust_block()
    if trust is not None:
        # Refused whole, as ``supply_rules`` refuses one: reporting shape problems in content
        # nobody has approved reads as a list of things to fix when the one thing to fix is
        # the approval.
        return None, (trust,)

    clearance = reader.route(CLEARANCE_ROUTE, states_axis=True)
    creepage = reader.route(CREEPAGE_ROUTE, states_axis=False)
    level_axes = reader.level_axes(clearance)

    blocks = tuple(reader.blocks)
    if clearance is None or creepage is None or level_axes is None:
        return None, blocks
    return ReinforcedRuleSet(clearance=clearance, creepage=creepage, level_axes=level_axes), blocks


class _PackageReader:
    """One pass over one package, collecting every block instead of raising at the first."""

    def __init__(self, package: RulePackage) -> None:
        self._package = package
        self.blocks: list[ReinforcedRuleBlock] = []

    def trust_block(self) -> ReinforcedRuleBlock | None:
        manifest = self._package.manifest
        if not manifest.approved:
            return ReinforcedRuleBlock(
                code=ReinforcedRuleBlockCode.PACKAGE_NOT_APPROVED,
                message="The active rule package is not approved.",
            )
        if not manifest.compatible:
            return ReinforcedRuleBlock(
                code=ReinforcedRuleBlockCode.PACKAGE_NOT_COMPATIBLE,
                message="The active rule package was built by an incompatible importer.",
            )
        return None

    def route(self, rule_id: str, *, states_axis: bool) -> DecisionRule | None:
        rule = next((item for item in self._package.decisions if item.id == rule_id), None)
        if rule is None:
            self.blocks.append(
                ReinforcedRuleBlock(
                    code=ReinforcedRuleBlockCode.RULE_MISSING,
                    semantic_rule_id=rule_id,
                    message=f"The active package carries no {rule_id} decision rule.",
                )
            )
            return None
        declared_inputs = {item.name for item in rule.inputs}
        if declared_inputs != _INPUTS:
            self._shape(
                rule_id,
                f"is resolved by {sorted(_INPUTS)} and declares {sorted(declared_inputs)}",
            )
            return None
        declared_outputs = {item.name for item in rule.outputs}
        missing = _OUTPUTS - declared_outputs
        if missing:
            self._shape(rule_id, f"states none of {sorted(missing)}")
            return None
        if states_axis and _AXIS_OUTPUT not in declared_outputs:
            self._shape(rule_id, f"states no {_AXIS_OUTPUT} for a step to follow")
            return None
        modes = next(item for item in rule.outputs if item.name == "treatment_mode").allowed_values
        unknown = set(modes) - {MULTIPLY, NEXT_LEVEL_IN_REQUIREMENT_AXIS}
        if unknown:
            # A third kind of treatment is one this application has no algorithm for, and
            # multiplying by whatever the row happens to carry is not it.
            self._shape(rule_id, f"states {sorted(unknown)}, which nothing here can carry out")
            return None
        return rule

    def level_axes(self, clearance: DecisionRule | None) -> dict[str, tuple[Decimal, ...]] | None:
        """The coordinates of every requirement the clearance route's rows defer to.

        Followed from the rule rather than named here, which is what keeps the axis a
        reviewed decision instead of one more constant in this file.
        """

        if clearance is None:
            return None
        referenced = {
            value.reference
            for row in clearance.rows
            for value in row.values
            if value.name == _AXIS_OUTPUT and value.reference is not None
        }
        resolved: dict[str, tuple[Decimal, ...]] = {}
        for rule_id in sorted(referenced):
            table = next((item for item in self._package.tables if item.id == rule_id), None)
            if table is None:
                self.blocks.append(
                    ReinforcedRuleBlock(
                        code=ReinforcedRuleBlockCode.RULE_MISSING,
                        semantic_rule_id=rule_id,
                        message=(
                            f"The active package's {clearance.id} steps along {rule_id}, "
                            "which the package does not carry as a table."
                        ),
                    )
                )
                continue
            if table.row_axis.id != _LEVEL_AXIS_ID or table.row_axis.unit != _VOLTAGE_UNIT:
                self._shape(
                    rule_id,
                    f"is not keyed by a {_VOLTAGE_UNIT} {_LEVEL_AXIS_ID} row axis to step along",
                )
                continue
            resolved[rule_id] = tuple(sorted(table.row_axis.values))
        return None if len(resolved) != len(referenced) else resolved

    def _shape(self, rule_id: str, detail: str) -> None:
        self.blocks.append(
            ReinforcedRuleBlock(
                code=ReinforcedRuleBlockCode.UNEXPECTED_SHAPE,
                semantic_rule_id=rule_id,
                message=f"The active package's {rule_id} {detail}.",
            )
        )


__all__ = [
    "CLEARANCE_ROUTE",
    "CREEPAGE_ROUTE",
    "MULTIPLY",
    "NEXT_LEVEL_IN_REQUIREMENT_AXIS",
    "READ_SEMANTIC_IDS",
    "ReinforcedRuleBlock",
    "ReinforcedRuleBlockCode",
    "ReinforcedRuleSet",
    "ReinforcedTreatment",
    "ReinforcedTreatmentUnavailable",
    "apply_reinforced_treatment",
    "multiply_stress",
    "next_preferred_level",
    "read_reinforced_rules",
    "reinforced_rule_blocks",
]
