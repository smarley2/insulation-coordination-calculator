"""Reads decisive-voltage-class (DVC) facts from the active rule package.

Table 2 and Table 3 of IEC 62477-1:2022 key their rows by decisive voltage class. This
module is the one place that maps :class:`DecisiveVoltageClass` to the anonymous
``dvc-N`` row token the importer's projection uses (see
``rules/importer/recipes/iec62477_1_2022/projection.py``); nothing else in the
application is allowed to know that mapping. Every other fact is read from the active
:class:`~insulation_coordination.domain.rules.RulePackage` through
:func:`~insulation_coordination.rules.evaluator.evaluate_decision` - never from a
constant - and a missing rule, an unapproved package, or a package from the wrong
edition degrades to a stated reason rather than a guess or a crash.
"""

from __future__ import annotations

from collections.abc import Mapping
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

# Maintainer confirmed 2026-08-11: Table 2 has four data rows, in this order - DVC A-s
# under wet and salt-water-wet conditions, DVC A-s dry, DVC B, DVC C - and the
# projection's row token for data row N is f"dvc-{N}". Per the maintainer's ruling,
# DecisiveVoltageClass.DVC_AS shows the dry row (dvc-2); the wet/salt-water-wet row
# exists in the source but has no enum member of its own, so nothing in this
# application can read it. The one place that says so in prose is
# insulation_coordination.ui.dvc_guide.
VOLTAGE_LIMITS_ROW_TOKENS: Mapping[DecisiveVoltageClass, Identifier] = {
    DecisiveVoltageClass.DVC_AS: "dvc-2",
    DecisiveVoltageClass.DVC_B: "dvc-3",
    DecisiveVoltageClass.DVC_C: "dvc-4",
}

# Maintainer confirmed 2026-08-11 which quantity each of Table 2's five data columns
# holds, and the projection's column token for data column N is f"voltage-quantity-{N}".
# The labels below are this application's own wording for those quantities, never the
# source's column headings: a heading is licensed text and may not be committed to this
# public repository, so each one describes the quantity in our words instead.
VOLTAGE_QUANTITY_COLUMN_TOKENS: tuple[tuple[Identifier, str], ...] = (
    ("voltage-quantity-1", "continuous AC working voltage, RMS"),
    ("voltage-quantity-2", "continuous AC working voltage, peak"),
    ("voltage-quantity-3", "continuous DC working voltage, mean"),
    ("voltage-quantity-4", "withstand level for a transient impulse"),
    ("voltage-quantity-5", "limit while a fault or abnormal operation persists"),
)

# Assumption, not a maintainer confirmation: Table 3 has three data rows
# (TABLE_3.expected_data_rows == 3), one per decisive voltage class, and this mapping
# assumes they follow the same A-s / B / C order Table 2 uses. That order has not been
# verified against the source and should be confirmed before it is relied on beyond
# this guide.
PROTECTION_MATRIX_ROW_TOKENS: Mapping[DecisiveVoltageClass, Identifier] = {
    DecisiveVoltageClass.DVC_AS: "dvc-1",
    DecisiveVoltageClass.DVC_B: "dvc-2",
    DecisiveVoltageClass.DVC_C: "dvc-3",
}

# PROTECTION_MATRIX_ROW_TOKENS is unconfirmed (see the comment above it), yet the guide
# cites a source for whatever it renders - inviting trust the mapping hasn't earned. Until
# a maintainer confirms Table 3's row order, protection_relationships withholds its result
# instead of rendering off an unverified mapping. Flip this to True once that confirmation
# lands; the mapping and the evaluation code beneath it are already in place.
PROTECTION_MATRIX_ROW_ORDER_CONFIRMED = False

_PROTECTION_MATRIX_UNCONFIRMED_REASON = (
    f"The decisive-voltage-class-to-row mapping {ids.DVC_PROTECTION_MATRIX} depends on "
    "has not been confirmed against the source, so this section is withheld rather "
    "than shown."
)

_VOLTAGE_LIMITS_RULE_IDS: tuple[Identifier, ...] = (
    ids.DVC_VOLTAGE_LIMITS,
    f"{ids.DVC_VOLTAGE_LIMITS}.fault_time_reference",
    f"{ids.DVC_VOLTAGE_LIMITS}.impulse_reference",
    f"{ids.DVC_VOLTAGE_LIMITS}.not_applicable",
)

_NOT_EVALUATED_REASON = "No decisive voltage class has been assigned; there is nothing to show."

DvcQuantityStatus = Literal["value", "reference", "not_applicable", "unavailable"]


class DvcVoltageQuantity(FrozenModel):
    """One Table 2 cell for a decisive voltage class: a number, a reference, or N/A."""

    label: str
    status: DvcQuantityStatus
    value: DecimalValue | None = None
    unit: Identifier | None = None
    reference_rule_id: Identifier | None = None
    source: SourceReference | None = None


class DvcLimitSummary(FrozenModel):
    """The Table 2 row for one decisive voltage class, or why it cannot be shown."""

    dvc: DecisiveVoltageClass
    available: bool
    reason: str = ""
    quantities: tuple[DvcVoltageQuantity, ...] = ()


class ProtectionGuidance(FrozenModel):
    """One Table 3 cell: the protection requirement for one protection context."""

    protection_context: Identifier
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
        try:
            unit = _declared_unit(rules[ids.DVC_VOLTAGE_LIMITS])
        except (StopIteration, IndexError):
            return DvcLimitSummary(
                dvc=dvc,
                available=False,
                reason=(
                    f"The active package's {ids.DVC_VOLTAGE_LIMITS} rule does not "
                    "declare a unit as expected."
                ),
            )
        row = VOLTAGE_LIMITS_ROW_TOKENS[dvc]
        quantities = tuple(
            self._quantity(rules, row, column, label, unit)
            for column, label in VOLTAGE_QUANTITY_COLUMN_TOKENS
        )
        return DvcLimitSummary(dvc=dvc, available=True, quantities=quantities)

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
        if not PROTECTION_MATRIX_ROW_ORDER_CONFIRMED:
            return DvcProtectionSummary(
                dvc=dvc, available=False, reason=_PROTECTION_MATRIX_UNCONFIRMED_REASON
            )
        row = PROTECTION_MATRIX_ROW_TOKENS[dvc]
        try:
            context_input = next(item for item in rule.inputs if item.name == "protection_context")
        except StopIteration:
            return DvcProtectionSummary(
                dvc=dvc,
                available=False,
                reason=(
                    f"The active package's {ids.DVC_PROTECTION_MATRIX} rule does not "
                    "declare protection contexts as expected."
                ),
            )
        relationships = []
        for context in context_input.allowed_values:
            result = _evaluate_safe(rule, {"dvc": row, "protection_context": context})
            if result is None or result.status != "matched":
                continue
            value = result.values[0]
            if value.categorical is None or result.source is None:
                continue
            relationships.append(
                ProtectionGuidance(
                    protection_context=context,
                    requirement=value.categorical,  # type: ignore[arg-type]
                    source=result.source,
                )
            )
        return DvcProtectionSummary(
            dvc=dvc, available=True, relationships=tuple(relationships)
        )

    def _quantity(
        self,
        rules: Mapping[Identifier, DecisionRule],
        row: str,
        column: str,
        label: str,
        unit: str,
    ) -> DvcVoltageQuantity:
        inputs = {"dvc": row, "voltage_quantity": column, "unit": unit}
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
                source=fault_time.source,
            )
        impulse = _evaluate_safe(rules[f"{ids.DVC_VOLTAGE_LIMITS}.impulse_reference"], inputs)
        if impulse is not None and impulse.status == "matched":
            # The rule carries an AC and a DC reference, and the guide has no supply to
            # choose between them: it names the base rule, which is the one a reader can
            # look up, and leaves the AC/DC split to whoever has a system voltage in hand.
            return DvcVoltageQuantity(
                label=label,
                status="reference",
                reference_rule_id=ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC,
                source=impulse.source,
            )
        not_applicable = _evaluate_safe(rules[f"{ids.DVC_VOLTAGE_LIMITS}.not_applicable"], inputs)
        if not_applicable is not None and not_applicable.status == "matched":
            return DvcVoltageQuantity(
                label=label, status="not_applicable", source=not_applicable.source
            )
        return DvcVoltageQuantity(label=label, status="unavailable")

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


def _from_expected_edition(rule: DecisionRule) -> bool:
    return rule.source.standard == STANDARD and rule.source.edition == EDITION


def _edition_reason(rule: DecisionRule) -> str:
    return (
        f"The active package's {rule.id} rule is from {rule.source.standard} "
        f"{rule.source.edition}, not {STANDARD} {EDITION}."
    )


def _declared_unit(rule: DecisionRule) -> str:
    unit_input = next(item for item in rule.inputs if item.name == "unit")
    return unit_input.allowed_values[0]


def _evaluate_safe(rule: DecisionRule, inputs: dict[str, str]) -> DecisionResult | None:
    try:
        return evaluate_decision(rule, inputs)
    except EvaluationError:
        return None


__all__ = [
    "PROTECTION_MATRIX_ROW_ORDER_CONFIRMED",
    "PROTECTION_MATRIX_ROW_TOKENS",
    "VOLTAGE_LIMITS_ROW_TOKENS",
    "VOLTAGE_QUANTITY_COLUMN_TOKENS",
    "DvcGuidanceService",
    "DvcLimitSummary",
    "DvcProtectionSummary",
    "DvcQuantityStatus",
    "DvcVoltageQuantity",
    "ProtectionGuidance",
]
