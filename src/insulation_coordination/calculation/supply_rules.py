"""Resolves the IEC 62477-1:2022 supply rules the stress derivation runs on.

This is the one seam between a rule package and everything issue #36 computes. It holds no
normative content of its own: no voltage, no band, no category step, no threshold. What it
holds is the *shape* each rule must have for this application to ask its question - the input
names it supplies, the output names it reads, the axis a lookup selects on - and the refusal
that follows when a package does not have it.

Nothing here falls back. A package that is absent, unapproved, incompatible, from the wrong
edition, missing a rule, or carrying a rule shaped differently from the one this application
resolves produces a :class:`SupplyRuleBlock` naming the reason, and
:func:`read_supply_rules` raises with the complete list. There is no constant to reach for
instead, which is the whole point: a derived impulse that came from a guess would look exactly
like one that came from the standard.

Every block is collected before raising, so a reviewer fixing an installation sees everything
that is wrong with it at once.

**What this adapter deliberately does not read** is recorded in :data:`RULES_READ_ELSEWHERE`.

**Routes.** Several of the required identifiers are not themselves rule ids: the approved
package projects one or more *routes* beneath them, and it is the routes a consumer resolves.
Table 7 projects an AC and a DC lookup per quantity; the reduction identifier projects one
route per subclause. The route names are built here from the identifier in
:mod:`~insulation_coordination.rules.importer.iec62477_2022.semantic_ids`, never invented
beside it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from insulation_coordination.calculation.clearance import CalculationError
from insulation_coordination.domain.frozen_model import FrozenModel
from insulation_coordination.domain.rules import (
    DecisionRule,
    Formula,
    RulePackage,
    SourceReference,
    Table,
    TableSelect,
    Variable,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.iec62477_2022.inventory import EDITION, STANDARD

#: Which of Table 7's two parallel row axes a question is asked against. A supply arrangement
#: resolves to one of these before any lookup happens; the two are separate tables, and a
#: value from one is never read off the other.
SupplyForm = Literal["ac", "dc"]

SUPPLY_FORMS: tuple[SupplyForm, ...] = ("ac", "dc")

#: The reduction identifier's routes, one per subclause the package projects beneath it. The
#: base identifier carries no rule of its own, so a consumer that asked for it by name would
#: find nothing and could not say which subclause was missing.
SPD_MAINS_ROUTE = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains"
SPD_NON_MAINS_ROUTE = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains"
SPD_MONITORING_ROUTE = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring"
#: The second rule a reduction route projects when its clause states what a degradable
#: reducing device owes. A route whose clause states nothing about it projects no such rule,
#: which is why the resolved field is optional - see :class:`SpdReductionRules`.
SPD_DEVICE_MONITORING_SUFFIX = "device_monitoring"

#: Required identifiers issue #36 lists that this adapter does not resolve, and why.
#:
#: ``clearance.requirements`` is consumed by the existing clearance engine through its own
#: approved compatibility mappings, not by supply stress derivation.
#:
#: ``high_frequency.applicability`` decides whether the high-frequency annex applies to a
#: pair at all, which is a question the Part 4 route asks, not one a supply arrangement
#: answers. It is a different rule from the transformer attenuation this adapter does read.
#:
#: ``altitude.test_voltage_correction`` corrects *test* voltages for the altitude of a testing
#: laboratory and the inventory records issue #37 as its consumer. Issue #36's own constraint
#: is that altitude never modifies a source impulse or temporary overvoltage, so making a
#: supply derivation depend on it would block a derivable scenario for a rule it must not use.
#: The altitude rule #36 does reach - clearance correction - is applied by the existing engine
#: after candidate selection.
RULES_READ_ELSEWHERE: frozenset[str] = frozenset(
    {
        ids.CLEARANCE_REQUIREMENTS,
        ids.HIGH_FREQUENCY_APPLICABILITY,
        ids.ALTITUDE_TEST_VOLTAGE_CORRECTION,
    }
)

#: The identifiers this adapter resolves, base identifiers rather than their routes.
READ_SEMANTIC_IDS: frozenset[str] = frozenset(
    {
        ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
        ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC,
        ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE,
        ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION,
        ids.SUPPLY_VERIFIED_BARRIER_TRANSFER,
        ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS,
        ids.SUPPLY_HF_TRANSFORMER_ATTENUATION,
    }
)

# The question each decision rule is resolved by: exactly the inputs this application
# supplies, and the outputs it reads. The input set is compared for equality rather than
# containment because the evaluator answers ``input_required`` for any declared input a
# caller omits - a package declaring one more input than this application knows about cannot
# be asked anything at all, and saying so is better than every query returning nothing. The
# output set is compared for containment: an output nothing here reads is harmless.
_SYSTEM_VOLTAGE_INPUTS = frozenset(
    {
        "supply_kind",
        "phase_system",
        "earthing_arrangement",
        "input_topology",
        "calculation_purpose",
    }
)
_SYSTEM_VOLTAGE_OUTPUTS = frozenset({"system_voltage_measure"})

_PROPAGATION_INPUTS = frozenset(
    {
        "evaluated_side",
        "mains_overvoltage_category",
        "non_mains_overvoltage_category",
        "galvanic_isolation_present",
    }
)
_PROPAGATION_OUTPUTS = frozenset(
    {"source_requirement", "transferred_requirement", "governing_requirement"}
)

_BARRIER_INPUTS = frozenset(
    {"galvanic_isolation_verified", "isolation_evidence_kind", "downstream_connection_kind"}
)
_BARRIER_OUTPUTS = frozenset(
    {"transfer_permitted", "combined_circuit_requirement", "propagates_to_connected_circuits"}
)

_SPD_REDUCTION_INPUTS = frozenset(
    {"source_overvoltage_category", "insulation_class", "part_of_category_reduction"}
)
_SPD_REDUCTION_OUTPUTS = frozenset({"reduction_permitted", "reduced_category"})

_SPD_MONITORING_INPUTS = frozenset(
    {"device_placement", "insulation_class", "device_degradable", "part_of_category_reduction"}
)
_SPD_MONITORING_OUTPUTS = frozenset(
    {"monitoring_required", "status_indication_required", "verification_reference"}
)

_SPD_DEVICE_MONITORING_INPUTS = frozenset({"device_degradable"})
_SPD_DEVICE_MONITORING_OUTPUTS = frozenset(
    {"monitoring_required", "status_indication_required", "monitoring_reference"}
)

_HF_TRANSFORMER_INPUTS = frozenset(
    {"circuit_dvc", "transformer_frequency_hz", "isolation_provided", "attenuation_evidence_kind"}
)
_HF_TRANSFORMER_OUTPUTS = frozenset({"working_voltage_basis_permitted", "required_evidence_kinds"})

#: The column each Table 7 lookup selects on, and the canonical unit both quantities carry.
_IMPULSE_COLUMN_AXIS = "overvoltage_category"
_TOV_COLUMN_AXIS = "tov_basis"
_VOLTAGE_UNIT = "V"


class SupplyRuleBlockCode(StrEnum):
    """Why a supply rule cannot be resolved. Typed, so a caller reports without parsing."""

    NO_PACKAGE = "no_package"
    PACKAGE_NOT_APPROVED = "package_not_approved"
    PACKAGE_NOT_COMPATIBLE = "package_not_compatible"
    RULE_MISSING = "rule_missing"
    WRONG_EDITION = "wrong_edition"
    UNEXPECTED_SHAPE = "unexpected_shape"


class SupplyRuleBlock(FrozenModel):
    """One reason the supply derivation cannot run against the active package."""

    code: SupplyRuleBlockCode
    message: str
    semantic_rule_id: str | None = None


class SupplyRulesUnavailable(CalculationError):
    """The active package cannot answer the supply questions this application asks of it.

    Carries every block rather than the first, because an installation is fixed by seeing the
    whole list. A :class:`~insulation_coordination.calculation.clearance.CalculationError`, so
    the engine catches it exactly as it already catches an unusable rule package.
    """

    def __init__(self, blocks: tuple[SupplyRuleBlock, ...]) -> None:
        self.blocks = blocks
        detail = "; ".join(f"{block.code.value}: {block.message}" for block in blocks)
        super().__init__(f"supply rules unavailable: {detail}")

    @property
    def codes(self) -> tuple[SupplyRuleBlockCode, ...]:
        return tuple(block.code for block in self.blocks)


class SupplyLookup(FrozenModel):
    """One Table 7 lookup: the reviewed formula, and the table it selects a cell from."""

    formula: Formula
    table: Table


class SupplyLookupPair(FrozenModel):
    """The AC and DC lookups of one quantity. Two tables, never one read two ways."""

    ac: SupplyLookup
    dc: SupplyLookup

    def for_form(self, form: SupplyForm) -> SupplyLookup:
        return self.ac if form == "ac" else self.dc


class SpdReductionRules(FrozenModel):
    """The reduction identifier's routes, resolved.

    ``mains_device_monitoring`` and ``non_mains_device_monitoring`` are optional because a
    reduction route projects one only when its own clause states what a degradable reducing
    device owes. A consumer that needs one and finds ``None`` must block and say so; it must
    not conclude that no monitoring is required.
    """

    mains: DecisionRule
    non_mains: DecisionRule
    monitoring: DecisionRule
    mains_device_monitoring: DecisionRule | None = None
    non_mains_device_monitoring: DecisionRule | None = None


class SupplyRuleSet(FrozenModel):
    """Every supply rule the derivation reads, resolved from one approved package.

    Nothing here is optional except where an absence is itself a reviewed answer, so a
    consumer holding this object never has to ask whether a rule arrived.
    """

    system_voltage_resolution: DecisionRule
    impulse: SupplyLookupPair
    temporary_overvoltage: SupplyLookupPair
    multiple_source_propagation: DecisionRule
    verified_barrier_transfer: DecisionRule
    spd_reduction: SpdReductionRules
    hf_transformer_attenuation: DecisionRule


def supply_rule_blocks(package: RulePackage | None) -> tuple[SupplyRuleBlock, ...]:
    """Every reason ``package`` cannot answer this application's supply questions.

    Empty means :func:`read_supply_rules` will succeed. For a caller that renders the reasons
    rather than aborting on them - the project page shows why a supply table is inert.
    """

    return _resolve(package)[1]


def read_supply_rules(package: RulePackage | None) -> SupplyRuleSet:
    """The supply rules resolved from ``package``, or a raised block listing every reason not.

    ``None`` is the state where no package is loaded at all, and blocks exactly like a package
    that is loaded but unapproved: neither can be derived from, and neither may be substituted
    for.
    """

    resolved, blocks = _resolve(package)
    if resolved is None:
        raise SupplyRulesUnavailable(blocks)
    return resolved


def _resolve(
    package: RulePackage | None,
) -> tuple[SupplyRuleSet | None, tuple[SupplyRuleBlock, ...]]:
    if package is None:
        return None, (
            SupplyRuleBlock(
                code=SupplyRuleBlockCode.NO_PACKAGE,
                message="No rule package is loaded.",
            ),
        )
    reader = _PackageReader(package)
    trust = reader.trust_block()
    if trust is not None:
        # An unapproved or incompatible package is refused whole. Resolving its rules anyway
        # would report shape problems in content nobody has approved, which reads as a list of
        # things to fix when the one thing to fix is the approval.
        return None, (trust,)

    system_voltage = reader.decision(
        ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
        inputs=_SYSTEM_VOLTAGE_INPUTS,
        outputs=_SYSTEM_VOLTAGE_OUTPUTS,
    )
    impulse = reader.lookup_pair(
        ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC,
        column_axis_id=_IMPULSE_COLUMN_AXIS,
        # Table 7's impulse bands are selected, never interpolated between. The prohibition is
        # enforced at this seam so no derivation has to remember it.
        interpolable=False,
    )
    temporary_overvoltage = reader.lookup_pair(
        ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE,
        column_axis_id=_TOV_COLUMN_AXIS,
        interpolable=True,
    )
    propagation = reader.decision(
        ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION,
        inputs=_PROPAGATION_INPUTS,
        outputs=_PROPAGATION_OUTPUTS,
    )
    barrier = reader.decision(
        ids.SUPPLY_VERIFIED_BARRIER_TRANSFER,
        inputs=_BARRIER_INPUTS,
        outputs=_BARRIER_OUTPUTS,
    )
    spd = reader.spd_reduction_rules()
    transformer = reader.decision(
        ids.SUPPLY_HF_TRANSFORMER_ATTENUATION,
        inputs=_HF_TRANSFORMER_INPUTS,
        outputs=_HF_TRANSFORMER_OUTPUTS,
    )

    blocks = tuple(reader.blocks)
    if (
        system_voltage is None
        or impulse is None
        or temporary_overvoltage is None
        or propagation is None
        or barrier is None
        or spd is None
        or transformer is None
    ):
        return None, blocks
    return (
        SupplyRuleSet(
            system_voltage_resolution=system_voltage,
            impulse=impulse,
            temporary_overvoltage=temporary_overvoltage,
            multiple_source_propagation=propagation,
            verified_barrier_transfer=barrier,
            spd_reduction=spd,
            hf_transformer_attenuation=transformer,
        ),
        blocks,
    )


class _PackageReader:
    """One pass over one package, collecting every block instead of raising at the first."""

    def __init__(self, package: RulePackage) -> None:
        self._package = package
        self.blocks: list[SupplyRuleBlock] = []

    def trust_block(self) -> SupplyRuleBlock | None:
        manifest = self._package.manifest
        if not manifest.approved:
            return SupplyRuleBlock(
                code=SupplyRuleBlockCode.PACKAGE_NOT_APPROVED,
                message="The active rule package is not approved.",
            )
        if not manifest.compatible:
            return SupplyRuleBlock(
                code=SupplyRuleBlockCode.PACKAGE_NOT_COMPATIBLE,
                message="The active rule package was built by an incompatible importer.",
            )
        return None

    def decision(
        self,
        rule_id: str,
        *,
        inputs: frozenset[str],
        outputs: frozenset[str],
        required: bool = True,
    ) -> DecisionRule | None:
        rule = next((item for item in self._package.decisions if item.id == rule_id), None)
        if rule is None:
            if required:
                self._missing(rule_id, "decision rule")
            return None
        if not self._same_edition(rule.source):
            self._wrong_edition(rule_id, rule.source)
            return None
        declared_inputs = {item.name for item in rule.inputs}
        if declared_inputs != inputs:
            self._shape(
                rule_id,
                f"is resolved by {sorted(inputs)} and declares {sorted(declared_inputs)}",
            )
            return None
        missing_outputs = outputs - {item.name for item in rule.outputs}
        if missing_outputs:
            self._shape(rule_id, f"states none of {sorted(missing_outputs)}")
            return None
        return rule

    def spd_reduction_rules(self) -> SpdReductionRules | None:
        mains = self.decision(
            SPD_MAINS_ROUTE, inputs=_SPD_REDUCTION_INPUTS, outputs=_SPD_REDUCTION_OUTPUTS
        )
        non_mains = self.decision(
            SPD_NON_MAINS_ROUTE, inputs=_SPD_REDUCTION_INPUTS, outputs=_SPD_REDUCTION_OUTPUTS
        )
        monitoring = self.decision(
            SPD_MONITORING_ROUTE, inputs=_SPD_MONITORING_INPUTS, outputs=_SPD_MONITORING_OUTPUTS
        )
        if mains is None or non_mains is None or monitoring is None:
            return None
        return SpdReductionRules(
            mains=mains,
            non_mains=non_mains,
            monitoring=monitoring,
            mains_device_monitoring=self._device_monitoring(SPD_MAINS_ROUTE),
            non_mains_device_monitoring=self._device_monitoring(SPD_NON_MAINS_ROUTE),
        )

    def _device_monitoring(self, route: str) -> DecisionRule | None:
        # Absent is a reviewed answer here, not a gap: a clause that states nothing about a
        # degradable reducing device projects no such rule. A rule that is present but shaped
        # wrongly still blocks, which is why this goes through the same shape gate.
        return self.decision(
            f"{route}.{SPD_DEVICE_MONITORING_SUFFIX}",
            inputs=_SPD_DEVICE_MONITORING_INPUTS,
            outputs=_SPD_DEVICE_MONITORING_OUTPUTS,
            required=False,
        )

    def lookup_pair(
        self,
        base_id: str,
        *,
        column_axis_id: str,
        interpolable: bool,
    ) -> SupplyLookupPair | None:
        resolved = {
            form: self._lookup(
                base_id, form, column_axis_id=column_axis_id, interpolable=interpolable
            )
            for form in SUPPLY_FORMS
        }
        if resolved["ac"] is None or resolved["dc"] is None:
            return None
        return SupplyLookupPair(ac=resolved["ac"], dc=resolved["dc"])

    def _lookup(
        self,
        base_id: str,
        form: SupplyForm,
        *,
        column_axis_id: str,
        interpolable: bool,
    ) -> SupplyLookup | None:
        formula_id = f"{base_id}.{form}.lookup"
        table_id = f"{base_id}.{form}"
        row_axis_id = f"system_voltage_{form}_v"
        formula = next((item for item in self._package.formulas if item.id == formula_id), None)
        if formula is None:
            self._missing(formula_id, "lookup formula")
            return None
        if not self._same_edition(formula.source):
            self._wrong_edition(formula_id, formula.source)
            return None
        expression = formula.expression
        if formula.unit != _VOLTAGE_UNIT or not isinstance(expression, TableSelect):
            self._shape(formula_id, f"is not a {_VOLTAGE_UNIT} selection from a semantic table")
            return None
        if (
            expression.table_id != table_id
            or not isinstance(expression.row, Variable)
            or expression.row.name != row_axis_id
            or not isinstance(expression.column, Variable)
            or expression.column.name != column_axis_id
            or expression.column_mode != "exact"
        ):
            self._shape(
                formula_id,
                f"does not select {table_id} by {row_axis_id} and an exact {column_axis_id}",
            )
            return None
        if not interpolable and expression.row_mode == "linear":
            self._shape(formula_id, "interpolates between bands the source does not interpolate")
            return None
        table = next((item for item in self._package.tables if item.id == table_id), None)
        if table is None:
            self._missing(table_id, "lookup table")
            return None
        if not self._same_edition(table.source):
            self._wrong_edition(table_id, table.source)
            return None
        if (
            table.unit != _VOLTAGE_UNIT
            or table.row_axis.id != row_axis_id
            or table.row_axis.unit != _VOLTAGE_UNIT
            or table.column_axis.id != column_axis_id
        ):
            self._shape(
                table_id,
                f"is not a {_VOLTAGE_UNIT} table keyed by {row_axis_id} and {column_axis_id}",
            )
            return None
        if not interpolable and table.interpolation != "none":
            self._shape(table_id, "declares interpolation the source does not permit")
            return None
        return SupplyLookup(formula=formula, table=table)

    def _same_edition(self, source: SourceReference) -> bool:
        return source.standard == STANDARD and source.edition == EDITION

    def _missing(self, rule_id: str, kind: str) -> None:
        self.blocks.append(
            SupplyRuleBlock(
                code=SupplyRuleBlockCode.RULE_MISSING,
                semantic_rule_id=rule_id,
                message=f"The active package carries no {rule_id} {kind}.",
            )
        )

    def _wrong_edition(self, rule_id: str, source: SourceReference) -> None:
        self.blocks.append(
            SupplyRuleBlock(
                code=SupplyRuleBlockCode.WRONG_EDITION,
                semantic_rule_id=rule_id,
                message=(
                    f"The active package's {rule_id} comes from {source.standard} "
                    f"{source.edition}, not {STANDARD} {EDITION}."
                ),
            )
        )

    def _shape(self, rule_id: str, detail: str) -> None:
        self.blocks.append(
            SupplyRuleBlock(
                code=SupplyRuleBlockCode.UNEXPECTED_SHAPE,
                semantic_rule_id=rule_id,
                message=f"The active package's {rule_id} {detail}.",
            )
        )


__all__ = [
    "READ_SEMANTIC_IDS",
    "RULES_READ_ELSEWHERE",
    "SPD_DEVICE_MONITORING_SUFFIX",
    "SPD_MAINS_ROUTE",
    "SPD_MONITORING_ROUTE",
    "SPD_NON_MAINS_ROUTE",
    "SUPPLY_FORMS",
    "SpdReductionRules",
    "SupplyForm",
    "SupplyLookup",
    "SupplyLookupPair",
    "SupplyRuleBlock",
    "SupplyRuleBlockCode",
    "SupplyRuleSet",
    "SupplyRulesUnavailable",
    "read_supply_rules",
    "supply_rule_blocks",
]
