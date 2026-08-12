"""Reads decisive-voltage-class (DVC) facts from the active rule package.

Table 2 and Table 3 of IEC 62477-1:2022 both key their rows by decisive voltage class and
their columns by a reviewed semantic selector (see
``rules/importer/recipes/iec62477_1_2022/projection.py``). This module resolves both against
that contract and nothing else: a class is selected by its own designation - a
:class:`DecisiveVoltageClass` member's value *is* the designation the package declares, so
there is no mapping table to keep - and a column by the quantity, basis, operating context
or protection target it carries. No physical row or column coordinate appears here, or
anywhere else in this application; those are extraction provenance, and a test enforces it.

Every fact is read from the active
:class:`~insulation_coordination.domain.rules.RulePackage` through
:func:`~insulation_coordination.rules.evaluator.evaluate_decision` - never from a
constant - and a missing rule, an unapproved package, a package from the wrong edition, or
a package whose rule does not carry the class at all degrades to a stated reason rather
than a guess or a crash.

Neither table is an exhaustive rule. Table 3 stopped being one when its single positional
context became six structured dimensions, whose combinations vastly outnumber the columns a
reviewer confirmed. A combination no reviewed column carries answers ``no_match``, and this
module reads that as "not a cell of the table" and omits it. It never becomes a rendered
requirement, a zero, or reported missing data.
"""

from __future__ import annotations

from collections.abc import Mapping
from itertools import product
from typing import Literal

from insulation_coordination.domain.enums import DecisiveVoltageClass
from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.quantities import DecimalValue
from insulation_coordination.domain.rules import (
    DecisionRule,
    Identifier,
    RulePackage,
    SourceReference,
)
from insulation_coordination.rules.evaluator import (
    DecisionResult,
    EvaluationError,
    evaluate_decision,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.iec62477_2022.inventory import EDITION, STANDARD

#: The value every selector dimension takes where it does not apply to a column.
NOT_APPLICABLE = "not_applicable"

#: Environments this application reads for a class, in the order it tries them. A
#: designation the package does not split by environment answers under
#: :data:`NOT_APPLICABLE`; one it does split answers under its dry reading. Maintainer's
#: ruling 2026-08-11: a wet or salt-water-wet reading has no
#: :class:`DecisiveVoltageClass` member of its own, so nothing in this application can
#: select it and nothing here does. The one place that says so in prose to a reader is
#: :mod:`insulation_coordination.ui.dvc_guide`.
READ_ENVIRONMENTS: tuple[str, ...] = (NOT_APPLICABLE, "dry")

#: Table 2's column dimensions, in the order this application enumerates and labels them.
VOLTAGE_QUANTITY_DIMENSIONS: tuple[str, ...] = ("quantity", "basis", "operating_context")

#: Table 3's column dimensions, in the same role.
PROTECTION_TARGET_DIMENSIONS: tuple[str, ...] = (
    "target",
    "pe_relationship",
    "access_context",
    "person_scope",
    "adjacent_dvc",
)

#: Every selector token either DVC table's reviewed columns can carry, in this
#: application's own words. One constant, so no consumer invents a second vocabulary and so
#: nothing here can drift towards the source's own column headings: each entry only spells
#: out a token that already exists in
#: :mod:`insulation_coordination.rules.importer.axis_selectors`, adding no reading of its
#: own. A token this map does not know still renders - as the token with its underscores
#: opened out - so a package that widens a vocabulary stays legible instead of going blank.
SELECTOR_TOKEN_LABELS: Mapping[str, str] = {
    "dvc_as": "DVC A-s",
    "dvc_b": "DVC B",
    "dvc_c": "DVC C",
    "dry": "dry",
    "wet_and_saltwater_wet": "wet and salt-water-wet",
    "normal": "normal operation",
    "single_fault_or_abnormal": "single fault or abnormal operation",
    "working_voltage": "working voltage",
    "impulse_withstand": "impulse withstand",
    "fault_voltage": "fault voltage",
    "ac_rms": "AC RMS",
    "ac_peak": "AC peak",
    "dc_mean": "DC mean",
    "ac_peak_or_dc": "AC peak or DC",
    "accessible_part": "accessible part",
    "adjacent_circuit": "adjacent circuit",
    "connected_to_pe": "connected to PE",
    "not_connected_to_pe": "not connected to PE",
    "general_access": "general access",
    "service_or_restricted_access": "service or restricted access",
    "ordinary_or_skilled": "ordinary or skilled persons",
    "skilled_only": "skilled persons only",
}

#: How one column's words are joined. A constant so a consumer can split a label apart
#: again rather than pinning the punctuation in a second place.
LABEL_SEPARATOR = ", "

_VOLTAGE_LIMITS_RULE_IDS: tuple[Identifier, ...] = (
    ids.DVC_VOLTAGE_LIMITS,
    f"{ids.DVC_VOLTAGE_LIMITS}.fault_time_reference",
    f"{ids.DVC_VOLTAGE_LIMITS}.impulse_reference",
    f"{ids.DVC_VOLTAGE_LIMITS}.not_applicable",
)

_NOT_EVALUATED_REASON = "No decisive voltage class has been assigned; there is nothing to show."

DvcQuantityStatus = Literal["value", "reference", "not_applicable"]

#: Which kind of rule a referring cell hands the question on to. Typed rather than left
#: for a reader to infer from the rule id, because the two are unresolved for different
#: reasons and a consumer must be able to say which without parsing a string:
#: ``supply_impulse`` needs project context this application resolves in issue #36, while
#: ``fault_time_curve`` is a time-voltage behaviour that never reduces to one limit.
DvcReferenceKind = Literal["supply_impulse", "fault_time_curve"]


def selector_label(*tokens: str) -> str:
    """This application's own words for one reviewed column, from its selector tokens.

    A :data:`NOT_APPLICABLE` dimension is dropped: a dimension that does not apply to a
    column is not part of what that column is.
    """
    words = [
        SELECTOR_TOKEN_LABELS.get(token, token.replace("_", " "))
        for token in tokens
        if token != NOT_APPLICABLE
    ]
    # ponytail: both tables declare one dimension that is never not_applicable, so the
    # empty case is unreachable today. The fallback is here so a widened vocabulary cannot
    # render a cell as a bare colon.
    return LABEL_SEPARATOR.join(words) or "unqualified"


class DvcVoltageQuantity(FrozenModel):
    """One Table 2 cell for a decisive voltage class: a number, a reference, or N/A."""

    label: str
    status: DvcQuantityStatus
    value: DecimalValue | None = None
    unit: Identifier | None = None
    reference_rule_id: Identifier | None = None
    reference_kind: DvcReferenceKind | None = None
    source: SourceReference | None = None


class DvcLimitSummary(FrozenModel):
    """The Table 2 row for one decisive voltage class, or why it cannot be shown."""

    dvc: DecisiveVoltageClass
    available: bool
    reason: str = ""
    quantities: tuple[DvcVoltageQuantity, ...] = ()


class ProtectionGuidance(FrozenModel):
    """One Table 3 cell: the protection requirement for one reviewed protection target."""

    label: str
    requirement: Literal["none", "basic_protection", "enhanced_protection"]
    source: SourceReference


class DvcProtectionSummary(FrozenModel):
    """The Table 3 row for one decisive voltage class, or why it cannot be shown."""

    dvc: DecisiveVoltageClass
    available: bool
    reason: str = ""
    relationships: tuple[ProtectionGuidance, ...] = ()


class DvcGuidanceService:
    """Reads DVC voltage limits and protection requirements from one rule package.

    Holds no IEC content of its own: every number and reference comes from evaluating
    the active package's own decision rules. ``package`` is ``None`` when no package is
    loaded at all, which degrades exactly like a package missing the DVC rules.
    """

    def __init__(self, package: RulePackage | None) -> None:
        self._package = package

    def limits(self, dvc: DecisiveVoltageClass) -> DvcLimitSummary:
        if dvc is DecisiveVoltageClass.NOT_EVALUATED:
            return DvcLimitSummary(dvc=dvc, available=False, reason=_NOT_EVALUATED_REASON)
        blocked = self._package_blocked_reason()
        if blocked is not None:
            return DvcLimitSummary(dvc=dvc, available=False, reason=blocked)
        rules: dict[Identifier, DecisionRule] = {}
        for rule_id in _VOLTAGE_LIMITS_RULE_IDS:
            rule = self._decision(rule_id)
            if rule is None:
                return DvcLimitSummary(
                    dvc=dvc,
                    available=False,
                    reason=f"{rule_id} is not available from the active package.",
                )
            if not _from_expected_edition(rule):
                return DvcLimitSummary(dvc=dvc, available=False, reason=_edition_reason(rule))
            rules[rule_id] = rule
        base = rules[ids.DVC_VOLTAGE_LIMITS]
        try:
            unit = _declared(base, "unit")[0]
            designations = _declared(base, "dvc")
            declared_environments = _declared(base, "environment")
            columns = _columns(base, VOLTAGE_QUANTITY_DIMENSIONS)
        except LookupError:
            return DvcLimitSummary(
                dvc=dvc, available=False, reason=_selector_reason(ids.DVC_VOLTAGE_LIMITS)
            )
        if dvc.value not in designations:
            return DvcLimitSummary(
                dvc=dvc, available=False, reason=_designation_reason(ids.DVC_VOLTAGE_LIMITS, dvc)
            )
        for environment in READ_ENVIRONMENTS:
            if environment not in declared_environments:
                continue
            quantities = []
            for label, selector in columns:
                inputs = {"dvc": dvc.value, "environment": environment, "unit": unit, **selector}
                quantity = self._quantity(rules, label, inputs)
                if quantity is not None:
                    quantities.append(quantity)
            if quantities:
                return DvcLimitSummary(dvc=dvc, available=True, quantities=tuple(quantities))
        return DvcLimitSummary(
            dvc=dvc, available=False, reason=_no_cell_reason(ids.DVC_VOLTAGE_LIMITS, dvc)
        )

    def protection_relationships(self, dvc: DecisiveVoltageClass) -> DvcProtectionSummary:
        if dvc is DecisiveVoltageClass.NOT_EVALUATED:
            return DvcProtectionSummary(dvc=dvc, available=False, reason=_NOT_EVALUATED_REASON)
        blocked = self._package_blocked_reason()
        if blocked is not None:
            return DvcProtectionSummary(dvc=dvc, available=False, reason=blocked)
        rule = self._decision(ids.DVC_PROTECTION_MATRIX)
        if rule is None:
            return DvcProtectionSummary(
                dvc=dvc,
                available=False,
                reason=f"{ids.DVC_PROTECTION_MATRIX} is not available from the active package.",
            )
        if not _from_expected_edition(rule):
            return DvcProtectionSummary(dvc=dvc, available=False, reason=_edition_reason(rule))
        try:
            designations = _declared(rule, "dvc")
            columns = _columns(rule, PROTECTION_TARGET_DIMENSIONS)
        except LookupError:
            return DvcProtectionSummary(
                dvc=dvc, available=False, reason=_selector_reason(ids.DVC_PROTECTION_MATRIX)
            )
        if dvc.value not in designations:
            return DvcProtectionSummary(
                dvc=dvc, available=False, reason=_designation_reason(ids.DVC_PROTECTION_MATRIX, dvc)
            )
        relationships = []
        for label, selector in columns:
            result = _evaluate_safe(rule, {"dvc": dvc.value, **selector})
            # no_match is the ordinary answer here, not a failure. Table 3 stopped being an
            # exhaustive rule when its one positional context became six structured
            # dimensions, so most combinations of the declared vocabularies are combinations
            # no reviewed column carries. Such a combination is not a cell of the table, so
            # it is omitted - never rendered as a requirement of its own.
            if result is None or result.status != "matched":
                continue
            value = result.values[0]
            if value.categorical is None or result.source is None:
                continue
            relationships.append(
                ProtectionGuidance(
                    label=label,
                    requirement=value.categorical,  # type: ignore[arg-type]
                    source=result.source,
                )
            )
        return DvcProtectionSummary(dvc=dvc, available=True, relationships=tuple(relationships))

    def _quantity(
        self,
        rules: Mapping[Identifier, DecisionRule],
        label: str,
        inputs: dict[str, str],
    ) -> DvcVoltageQuantity | None:
        numeric = _evaluate_safe(rules[ids.DVC_VOLTAGE_LIMITS], inputs)
        if numeric is not None and numeric.status == "matched":
            value = numeric.values[0]
            return DvcVoltageQuantity(
                label=label,
                status="value",
                value=value.numeric,
                unit=value.unit,
                source=numeric.source,
            )
        fault_time = _evaluate_safe(rules[f"{ids.DVC_VOLTAGE_LIMITS}.fault_time_reference"], inputs)
        if fault_time is not None and fault_time.status == "matched":
            return DvcVoltageQuantity(
                label=label,
                status="reference",
                reference_rule_id=fault_time.values[0].reference,
                reference_kind="fault_time_curve",
                source=fault_time.source,
            )
        impulse = _evaluate_safe(rules[f"{ids.DVC_VOLTAGE_LIMITS}.impulse_reference"], inputs)
        if impulse is not None and impulse.status == "matched":
            # A typed deferral, not a missing feature. The cell's requirement is whatever
            # the supply rule resolves from a system voltage and an overvoltage category,
            # and this application resolves those in issue #36; the rule also carries an AC
            # and a DC reference, so even choosing between them needs a supply. Naming the
            # base rule and the reason is the whole honest answer available here - guessing
            # a system voltage to print a number would be #36's work done wrongly.
            return DvcVoltageQuantity(
                label=label,
                status="reference",
                reference_rule_id=ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC,
                reference_kind="supply_impulse",
                source=impulse.source,
            )
        not_applicable = _evaluate_safe(rules[f"{ids.DVC_VOLTAGE_LIMITS}.not_applicable"], inputs)
        if not_applicable is not None and not_applicable.status == "matched":
            return DvcVoltageQuantity(
                label=label, status="not_applicable", source=not_applicable.source
            )
        # No route matched, so no reviewed column carries this combination for this class.
        # That is not missing data to report: under the semantic contract the combination
        # simply is not a cell. Omitting it is what keeps the guide from listing the whole
        # cartesian product of the declared vocabularies as gaps.
        return None

    def _decision(self, rule_id: Identifier) -> DecisionRule | None:
        if self._package is None:
            return None
        return next((rule for rule in self._package.decisions if rule.id == rule_id), None)

    def _package_blocked_reason(self) -> str | None:
        if self._package is None:
            return "No rule package is loaded."
        if not self._package.manifest.approved:
            return "The active rule package is not approved."
        return None


def _declared(rule: DecisionRule, name: str) -> tuple[str, ...]:
    """The values the rule declares for one input, or ``LookupError`` if it declares none."""
    for item in rule.inputs:
        if item.name == name:
            return item.allowed_values
    raise LookupError(name)


def _columns(
    rule: DecisionRule, dimensions: tuple[str, ...]
) -> tuple[tuple[str, dict[str, str]], ...]:
    """Every combination of the dimensions the rule declares, labelled in our own words.

    Built from the declared vocabularies rather than from the rule's rows, because a
    consumer resolves a rule through the evaluator and the evaluator answers one complete
    combination of declared inputs at a time. Most combinations answer ``no_match``; the
    caller drops those.
    """
    values = [_declared(rule, name) for name in dimensions]
    return tuple(
        (selector_label(*combination), dict(zip(dimensions, combination, strict=True)))
        for combination in product(*values)
    )


def _from_expected_edition(rule: DecisionRule) -> bool:
    return rule.source.standard == STANDARD and rule.source.edition == EDITION


def _edition_reason(rule: DecisionRule) -> str:
    return (
        f"The active package's {rule.id} rule is from {rule.source.standard} "
        f"{rule.source.edition}, not {STANDARD} {EDITION}."
    )


def _selector_reason(rule_id: Identifier) -> str:
    return (
        f"The active package's {rule_id} rule does not declare the selector inputs this "
        "application resolves it by."
    )


def _designation_reason(rule_id: Identifier, dvc: DecisiveVoltageClass) -> str:
    return (
        f"The active package's {rule_id} rule does not carry {selector_label(dvc.value)}, "
        "so there is nothing to show for this class."
    )


def _no_cell_reason(rule_id: Identifier, dvc: DecisiveVoltageClass) -> str:
    return (
        f"The active package's {rule_id} rule carries no reviewed cell for "
        f"{selector_label(dvc.value)} in any environment this application reads."
    )


def _evaluate_safe(rule: DecisionRule, inputs: dict[str, str]) -> DecisionResult | None:
    # ponytail: defensive only, now that every query is built from the rule's own declared
    # vocabularies - an unmatched combination answers no_match rather than raising. What is
    # left is a malformed package: a dimension declared numeric or boolean, which no string
    # can satisfy. Degrading that to "not a cell" keeps one bad rule out of the whole guide.
    try:
        return evaluate_decision(rule, inputs)
    except EvaluationError:
        return None


__all__ = [
    "LABEL_SEPARATOR",
    "NOT_APPLICABLE",
    "PROTECTION_TARGET_DIMENSIONS",
    "READ_ENVIRONMENTS",
    "SELECTOR_TOKEN_LABELS",
    "VOLTAGE_QUANTITY_DIMENSIONS",
    "DvcGuidanceService",
    "DvcLimitSummary",
    "DvcProtectionSummary",
    "DvcQuantityStatus",
    "DvcReferenceKind",
    "DvcVoltageQuantity",
    "ProtectionGuidance",
    "selector_label",
]
