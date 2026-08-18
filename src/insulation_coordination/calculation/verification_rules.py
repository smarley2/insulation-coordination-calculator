"""Resolves the IEC 62477-1:2022 rules the dielectric verification planning runs on.

This is the one seam between a rule package and everything issue #37 plans. It holds no
normative content of its own: no test voltage, no duration, no waveform, no acceptance
criterion, no classification decision. What it holds is the *shape* each rule must have for
this application to ask its question - the input names it supplies, the output names it reads,
the axes a table is keyed by, the kind of test a procedure says it is - and the refusal that
follows when a package does not have it.

Nothing here falls back. A package that is absent, unapproved, incompatible, from the wrong
edition, missing a rule, or carrying a rule shaped differently from the one this application
resolves produces a :class:`VerificationRuleBlock` naming the reason, and
:func:`read_verification_rules` raises with the complete list. A planned test schedule built
from a guessed value would look exactly like one built from the standard, which is the whole
reason there is no constant to reach for instead.

Every block is collected before raising, so a reviewer fixing an installation sees everything
that is wrong with it at once.

**Routes.** Most of the required identifiers are not themselves rule ids: the approved package
projects one or more *routes* beneath them, and it is the routes a consumer resolves. Table 26
projects one procedure per variant, Table 27 one selection table per column pair per supply
form, Tables 28 and 29 one table per test purpose per voltage form, and three of the clause
procedures project an applicability gate beside the procedure. Those route names are built
here from the identifiers in
:mod:`~insulation_coordination.rules.importer.iec62477_2022.semantic_ids`, exactly as
``supply_rules`` builds the reduction routes - never imported from the recipe that produces
them, which is extraction-side code this module must not depend on.

**What this adapter deliberately does not check** is the interpolation each table declares.
Whether a value between two tabulated rows may be resolved is stated by the source and carried
by the package, and a consumer reads it from the table it was handed. Restating it here would
put a source permission in application code for no gain, which is the failure mode issue #40
exists to prevent. ``supply_rules`` does gate on it because a supply derivation selects a band
directly; a verification plan presents whatever the package's own lookup resolves.

**What this adapter deliberately does not read** is recorded in :data:`RULES_READ_ELSEWHERE`.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Literal

from insulation_coordination.calculation.clearance import CalculationError
from insulation_coordination.domain.frozen_model import FrozenModel
from insulation_coordination.domain.rules import (
    DecisionRule,
    PiecewiseCurveRule,
    ProcedureRule,
    RulePackage,
    SourceReference,
    Table,
)
from insulation_coordination.domain.verification import TestClassification
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.iec62477_2022.inventory import EDITION, STANDARD

#: Which of two parallel axes a question is asked against. Tables 27, 28 and 29 each carry the
#: pair, but they carry it for two different reasons: Table 27's is the form of the *supply*
#: whose system voltage keys the row axis, while Tables 28 and 29 offer an AC and a DC column
#: for the same row. One name because a consumer selects with one word either way; the two
#: meanings are why this is not the ``SupplyForm`` that ``supply_rules`` resolves an
#: arrangement to.
VoltageForm = Literal["ac", "dc"]

VOLTAGE_FORMS: tuple[VoltageForm, ...] = ("ac", "dc")

#: Table 26's variants, in the order the source prints its condition columns. Neutral names
#: for what each column is about; the conditions themselves live in the package.
IMPULSE_PROCEDURE_VARIANTS: tuple[str, ...] = (
    "insulation_basic",
    "insulation_reinforced",
    "transient_reduction",
)
#: Table 27's column pairs, one per kind of circuit the selection is made for.
IMPULSE_SELECTION_PAIRS: tuple[str, ...] = ("mains_circuits", "non_mains_circuits")
#: The two test purposes Tables 28 and 29 both tabulate side by side. An enhanced-protection
#: type test may state a different value from the routine and basic-protection one, which is
#: why they are separate routes and never one value read twice.
DIELECTRIC_PURPOSES: tuple[str, ...] = ("routine_and_basic_type", "enhanced_type")

#: Preconditioning carries one gate and one procedure per source clause, because the two
#: clauses state different step inventories for different work. A consumer asks the gate and
#: is told which of the two routes to follow.
PRECONDITIONING_APPLICABILITY_ROUTE = f"{ids.TEST_PRECONDITIONING}.applicability"
PRECONDITIONING_ELECTRICAL_ROUTE = f"{ids.TEST_PRECONDITIONING}.electrical_tests"
PRECONDITIONING_MATERIAL_ROUTE = f"{ids.TEST_PRECONDITIONING}.material"
#: The gate each of these two procedures is conditioned on, projected from the same source
#: statement as the procedure itself.
FOIL_APPLICABILITY_ROUTE = f"{ids.TEST_ACCESSIBLE_SURFACE_FOIL}.applicability"
PARTIAL_DISCHARGE_APPLICABILITY_ROUTE = f"{ids.TEST_PARTIAL_DISCHARGE}.applicability"

#: The identifiers this adapter resolves: the thirteen issue #37 names as its rule dependency,
#: as base identifiers rather than their routes.
READ_SEMANTIC_IDS: frozenset[str] = frozenset(
    {
        ids.DVC_VOLTAGE_LIMITS,
        ids.DVC_PROTECTION_MATRIX,
        ids.DVC_FAULT_TIME_VOLTAGE,
        ids.TEST_WORKING_VOLTAGE_DETERMINATION,
        ids.TEST_IMPULSE_PROCEDURE,
        ids.TEST_IMPULSE_SELECTION,
        ids.TEST_MAINS_DIELECTRIC_VALUES,
        ids.TEST_NON_MAINS_DIELECTRIC_VALUES,
        ids.TEST_PARTIAL_DISCHARGE,
        ids.TEST_INTERNAL_SPD_MONITORING,
        ids.TEST_PRECONDITIONING,
        ids.TEST_ACCESSIBLE_SURFACE_FOIL,
        ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION,
    }
)

#: Identifiers a dielectric verification plan touches that this adapter does not resolve, and
#: why. Recorded rather than left to be rediscovered: each one is a plausible thing to look for
#: here and finding nothing would read as an omission.
#:
#: ``altitude.test_voltage_correction`` corrects a test voltage for the altitude of a testing
#: laboratory. It belongs to the impulse and dielectric planning of issue #37's later tasks and
#: is resolved there, against the test whose voltage it corrects, rather than up front - a plan
#: that has no altitude context yet must not block on a correction nothing has asked for.
#:
#: ``supply.tov_by_system_voltage`` is a supply-side quantity. A verification plan consumes the
#: temporary overvoltage that issue #36 already derived and traced, and reading the table a
#: second time here would give a plan the chance to disagree with the derivation it is
#: planning against.
#:
#: ``high_frequency.applicability`` decides whether the high-frequency annex applies to a pair,
#: which the existing engine answers before a verification plan exists.
RULES_READ_ELSEWHERE: frozenset[str] = frozenset(
    {
        ids.ALTITUDE_TEST_VOLTAGE_CORRECTION,
        ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE,
        ids.HIGH_FREQUENCY_APPLICABILITY,
    }
)

#: How a package names the three test classifications, and what this application calls them.
#: The translation lives here because this is the seam: nothing in ``domain/`` should have to
#: know a package's vocabulary, and nothing downstream should have to translate twice.
PACKAGE_CLASSIFICATIONS: Mapping[str, TestClassification] = {
    "type_test": TestClassification.TYPE,
    "routine_test": TestClassification.ROUTINE,
    "sample_test": TestClassification.SAMPLE,
}

# What each procedure says it is. A procedure resolved under one identifier that declares it
# performs a different test is two readings of the package disagreeing, and there is no
# precedence rule to apply - it blocks.
_WORKING_VOLTAGE_TEST_KIND = "working_voltage_determination"
_IMPULSE_TEST_KIND = "impulse_withstand_voltage"
_PARTIAL_DISCHARGE_TEST_KIND = "partial_discharge"
_INTERNAL_SPD_TEST_KIND = "internal_spd_monitoring"
_PRECONDITIONING_ELECTRICAL_TEST_KIND = "electrical_test_preconditioning"
_PRECONDITIONING_MATERIAL_TEST_KIND = "material_preconditioning"
_FOIL_TEST_KIND = "accessible_surface_foil_placement"

# The question each decision rule is resolved by: exactly the inputs this application supplies,
# and the outputs it reads. The input set is compared for equality rather than containment
# because the evaluator answers ``input_required`` for any declared input a caller omits - a
# package declaring one more input than this application knows about cannot be asked anything
# at all, and saying so is better than every query silently returning nothing. The output set
# is compared for containment: an output nothing here reads is harmless.
_PARTIAL_DISCHARGE_GATE_INPUTS = frozenset({"partial_discharge_test_voltage_declared"})
_PARTIAL_DISCHARGE_GATE_OUTPUTS = frozenset({"partial_discharge_test"})

_FOIL_GATE_INPUTS = frozenset({"non_conductive_accessible_surface_present"})
_FOIL_GATE_OUTPUTS = frozenset({"foil_wrap_required", "permitted_classification_substitution"})

_PRECONDITIONING_GATE_INPUTS = frozenset({"test_context", "test_purpose"})
_PRECONDITIONING_GATE_OUTPUTS = frozenset(
    {"preconditioning_required", "preconditioning_procedure_rule_id"}
)

_EXEMPTION_INPUTS = frozenset(
    {
        "sub_assembly_routine_test_performed",
        "assembly_shown_not_to_compromise_insulation",
        "assembled_type_test_passed",
    }
)
_EXEMPTION_OUTPUTS = frozenset({"assembled_routine_test_exempt"})

# The axes each selection table is keyed by, and the unit every one of them carries. A table
# read off the wrong axis would resolve a real number to the wrong question.
#
#: Table 27 keys its rows on the system voltage of the supply, so each form reads its own axis -
#: the same two parallel axes Table 7 carries. Tables 28 and 29 instead read one row axis with
#: an AC and a DC column, which is why this mapping is not shared with them.
IMPULSE_SELECTION_ROW_AXES: Mapping[VoltageForm, str] = {
    form: f"system_voltage_{form}_v" for form in VOLTAGE_FORMS
}
_IMPULSE_SELECTION_COLUMN_AXIS = "impulse_selection_column"
_DIELECTRIC_COLUMN_AXIS = "dielectric_test_column"
_MAINS_DIELECTRIC_ROW_AXIS = "system_voltage_v"
_NON_MAINS_DIELECTRIC_ROW_AXIS = "working_voltage_recurring_peak_v"
_VOLTAGE_UNIT = "V"


class VerificationRuleBlockCode(StrEnum):
    """Why a verification rule cannot be resolved. Typed, so a caller reports without parsing."""

    NO_PACKAGE = "no_package"
    PACKAGE_NOT_APPROVED = "package_not_approved"
    PACKAGE_NOT_COMPATIBLE = "package_not_compatible"
    RULE_MISSING = "rule_missing"
    WRONG_EDITION = "wrong_edition"
    UNEXPECTED_SHAPE = "unexpected_shape"


class VerificationRuleBlock(FrozenModel):
    """One reason verification planning cannot run against the active package."""

    code: VerificationRuleBlockCode
    message: str
    semantic_rule_id: str | None = None


class VerificationRulesUnavailable(CalculationError):
    """The active package cannot answer the verification questions this application asks.

    Carries every block rather than the first, because an installation is fixed by seeing the
    whole list. A :class:`~insulation_coordination.calculation.clearance.CalculationError`, so
    the engine catches it exactly as it already catches an unusable rule package.
    """

    def __init__(self, blocks: tuple[VerificationRuleBlock, ...]) -> None:
        self.blocks = blocks
        detail = "; ".join(f"{block.code.value}: {block.message}" for block in blocks)
        super().__init__(f"verification rules unavailable: {detail}")

    @property
    def codes(self) -> tuple[VerificationRuleBlockCode, ...]:
        return tuple(block.code for block in self.blocks)


class VoltageTablePair(FrozenModel):
    """The AC and DC tables of one route. Two tables, never one read two ways."""

    ac: Table
    dc: Table

    def for_form(self, form: VoltageForm) -> Table:
        return self.ac if form == "ac" else self.dc


class ImpulseProcedureRules(FrozenModel):
    """Table 26's procedure, one per variant.

    Kept apart rather than merged because the variants state different conditions for the same
    steps, and a plan for a reinforced implementation must not be able to pick up the basic
    variant's condition by accident.
    """

    insulation_basic: ProcedureRule
    insulation_reinforced: ProcedureRule
    transient_reduction: ProcedureRule


class ImpulseSelectionTables(FrozenModel):
    """Table 27's selection tables, one AC/DC pair per kind of circuit."""

    mains_circuits: VoltageTablePair
    non_mains_circuits: VoltageTablePair


class DielectricValueTables(FrozenModel):
    """One dielectric table's values, one AC/DC pair per test purpose.

    The enhanced-protection type test and the routine-and-basic-type test are separate routes
    on purpose: a plan that reused one value for both would be asserting an equality the source
    has not been asked for.
    """

    routine_and_basic_type: VoltageTablePair
    enhanced_type: VoltageTablePair


class GatedProcedure(FrozenModel):
    """A procedure and the decision that says whether it applies.

    The two are resolved together because the package projects them from one source statement.
    A consumer that had the procedure without its gate could only guess at applicability, and
    guessing is the failure this whole seam exists to prevent.
    """

    procedure: ProcedureRule
    applicability: DecisionRule


class PreconditioningRules(FrozenModel):
    """The gate, and the two procedures it selects between."""

    applicability: DecisionRule
    electrical_tests: ProcedureRule
    material: ProcedureRule


class VerificationRuleSet(FrozenModel):
    """Every rule the dielectric verification planning reads, from one approved package.

    Nothing here is optional. A consumer holding this object never has to ask whether a rule
    arrived, which is what lets the planning modules be about planning.
    """

    dvc_voltage_limits: DecisionRule
    dvc_protection_matrix: DecisionRule
    dvc_fault_time_voltage: PiecewiseCurveRule
    working_voltage_determination: ProcedureRule
    impulse_procedure: ImpulseProcedureRules
    impulse_selection: ImpulseSelectionTables
    mains_dielectric_values: DielectricValueTables
    non_mains_dielectric_values: DielectricValueTables
    partial_discharge: GatedProcedure
    internal_spd_monitoring: ProcedureRule
    preconditioning: PreconditioningRules
    accessible_surface_foil: GatedProcedure
    assembled_routine_exemption: DecisionRule


def classifications_of(procedure: ProcedureRule) -> tuple[TestClassification, ...]:
    """What this application calls the classifications ``procedure`` declares.

    Empty is a reviewed answer, not a gap: the package deliberately leaves a classification
    unstated where its cross-reference matrix has no row for the clause. A consumer reports
    that as unresolved rather than choosing one.

    Safe to call on any procedure this module resolved - an unknown classification name is
    refused at resolution time, so nothing here has to decide what to do with one.
    """

    return tuple(
        PACKAGE_CLASSIFICATIONS[name]
        for name in procedure.classifications
        if name in PACKAGE_CLASSIFICATIONS
    )


def verification_rule_blocks(package: RulePackage | None) -> tuple[VerificationRuleBlock, ...]:
    """Every reason ``package`` cannot answer this application's verification questions.

    Empty means :func:`read_verification_rules` will succeed. For a caller that renders the
    reasons rather than aborting on them - a report page shows why a verification section is
    empty instead of showing an empty section.
    """

    return _resolve(package)[1]


def read_verification_rules(package: RulePackage | None) -> VerificationRuleSet:
    """The verification rules resolved from ``package``, or a raised list of every reason not.

    ``None`` is the state where no package is loaded at all, and blocks exactly like a package
    that is loaded but unapproved: neither can be planned from, and neither may be substituted
    for.
    """

    resolved, blocks = _resolve(package)
    if resolved is None:
        raise VerificationRulesUnavailable(blocks)
    return resolved


def _resolve(
    package: RulePackage | None,
) -> tuple[VerificationRuleSet | None, tuple[VerificationRuleBlock, ...]]:
    if package is None:
        return None, (
            VerificationRuleBlock(
                code=VerificationRuleBlockCode.NO_PACKAGE,
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

    resolved = {
        "dvc_voltage_limits": reader.dvc_decision(ids.DVC_VOLTAGE_LIMITS),
        "dvc_protection_matrix": reader.dvc_decision(ids.DVC_PROTECTION_MATRIX),
        "dvc_fault_time_voltage": reader.curve(ids.DVC_FAULT_TIME_VOLTAGE),
        "working_voltage_determination": reader.procedure(
            ids.TEST_WORKING_VOLTAGE_DETERMINATION, test_kind=_WORKING_VOLTAGE_TEST_KIND
        ),
        "impulse_procedure": reader.impulse_procedures(),
        "impulse_selection": reader.impulse_selection_tables(),
        "mains_dielectric_values": reader.dielectric_tables(
            ids.TEST_MAINS_DIELECTRIC_VALUES, row_axis_id=_MAINS_DIELECTRIC_ROW_AXIS
        ),
        "non_mains_dielectric_values": reader.dielectric_tables(
            ids.TEST_NON_MAINS_DIELECTRIC_VALUES, row_axis_id=_NON_MAINS_DIELECTRIC_ROW_AXIS
        ),
        "partial_discharge": reader.gated_procedure(
            ids.TEST_PARTIAL_DISCHARGE,
            test_kind=_PARTIAL_DISCHARGE_TEST_KIND,
            gate_id=PARTIAL_DISCHARGE_APPLICABILITY_ROUTE,
            gate_inputs=_PARTIAL_DISCHARGE_GATE_INPUTS,
            gate_outputs=_PARTIAL_DISCHARGE_GATE_OUTPUTS,
        ),
        "internal_spd_monitoring": reader.procedure(
            ids.TEST_INTERNAL_SPD_MONITORING, test_kind=_INTERNAL_SPD_TEST_KIND
        ),
        "preconditioning": reader.preconditioning_rules(),
        "accessible_surface_foil": reader.gated_procedure(
            ids.TEST_ACCESSIBLE_SURFACE_FOIL,
            test_kind=_FOIL_TEST_KIND,
            gate_id=FOIL_APPLICABILITY_ROUTE,
            gate_inputs=_FOIL_GATE_INPUTS,
            gate_outputs=_FOIL_GATE_OUTPUTS,
        ),
        "assembled_routine_exemption": reader.decision(
            ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION,
            inputs=_EXEMPTION_INPUTS,
            outputs=_EXEMPTION_OUTPUTS,
        ),
    }

    blocks = tuple(reader.blocks)
    if any(value is None for value in resolved.values()):
        return None, blocks
    return VerificationRuleSet.model_validate(resolved), blocks


class _PackageReader:
    """One pass over one package, collecting every block instead of raising at the first."""

    def __init__(self, package: RulePackage) -> None:
        self._package = package
        self.blocks: list[VerificationRuleBlock] = []

    def trust_block(self) -> VerificationRuleBlock | None:
        manifest = self._package.manifest
        if not manifest.approved:
            return VerificationRuleBlock(
                code=VerificationRuleBlockCode.PACKAGE_NOT_APPROVED,
                message="The active rule package is not approved.",
            )
        if not manifest.compatible:
            return VerificationRuleBlock(
                code=VerificationRuleBlockCode.PACKAGE_NOT_COMPATIBLE,
                message="The active rule package was built by an incompatible importer.",
            )
        return None

    # --- decisions -------------------------------------------------------------------

    def decision(
        self, rule_id: str, *, inputs: frozenset[str], outputs: frozenset[str]
    ) -> DecisionRule | None:
        rule = self._present(rule_id, self._package.decisions, "decision rule")
        if rule is None:
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

    def dvc_decision(self, rule_id: str) -> DecisionRule | None:
        """A DVC decision, resolved for presence and edition only.

        The input and output contract of Tables 2 and 3 is owned by
        :class:`~insulation_coordination.domain.dvc.DvcGuidanceService`, which already resolves
        both against their reviewed selector dimensions. Restating that contract here would put
        it in two places, and asserting an input set this slice does not yet supply would block
        a good package over a question nothing asks. What a verification plan needs from this
        seam today is the guarantee that the rule is present and from the right edition, so
        that a Table 3 requirement it reports came from the standard it names.
        """

        return self._present(rule_id, self._package.decisions, "decision rule")

    # --- procedures ------------------------------------------------------------------

    def procedure(self, rule_id: str, *, test_kind: str) -> ProcedureRule | None:
        rule = self._present(rule_id, self._package.procedures, "procedure rule")
        if rule is None:
            return None
        if rule.test_kind != test_kind:
            self._shape(rule_id, f"performs {rule.test_kind!r} rather than {test_kind!r}")
            return None
        unknown = sorted(set(rule.classifications) - set(PACKAGE_CLASSIFICATIONS))
        if unknown:
            self._shape(
                rule_id, f"declares classifications this application cannot read: {unknown}"
            )
            return None
        return rule

    def gated_procedure(
        self,
        rule_id: str,
        *,
        test_kind: str,
        gate_id: str,
        gate_inputs: frozenset[str],
        gate_outputs: frozenset[str],
    ) -> GatedProcedure | None:
        procedure = self.procedure(rule_id, test_kind=test_kind)
        gate = self.decision(gate_id, inputs=gate_inputs, outputs=gate_outputs)
        if procedure is None or gate is None:
            return None
        if procedure.applicability_rule_id != gate_id:
            # A procedure pointing somewhere else is a package whose two halves came from
            # different readings. Blocking is the only honest answer: following the pointer
            # would resolve a gate nothing reviewed against this procedure.
            self._shape(
                rule_id,
                f"is gated on {procedure.applicability_rule_id!r} rather than {gate_id!r}",
            )
            return None
        return GatedProcedure(procedure=procedure, applicability=gate)

    def impulse_procedures(self) -> ImpulseProcedureRules | None:
        resolved = {
            variant: self.procedure(
                f"{ids.TEST_IMPULSE_PROCEDURE}.{variant}", test_kind=_IMPULSE_TEST_KIND
            )
            for variant in IMPULSE_PROCEDURE_VARIANTS
        }
        if any(rule is None for rule in resolved.values()):
            return None
        return ImpulseProcedureRules.model_validate(resolved)

    def preconditioning_rules(self) -> PreconditioningRules | None:
        applicability = self.decision(
            PRECONDITIONING_APPLICABILITY_ROUTE,
            inputs=_PRECONDITIONING_GATE_INPUTS,
            outputs=_PRECONDITIONING_GATE_OUTPUTS,
        )
        electrical = self.procedure(
            PRECONDITIONING_ELECTRICAL_ROUTE, test_kind=_PRECONDITIONING_ELECTRICAL_TEST_KIND
        )
        material = self.procedure(
            PRECONDITIONING_MATERIAL_ROUTE, test_kind=_PRECONDITIONING_MATERIAL_TEST_KIND
        )
        if applicability is None or electrical is None or material is None:
            return None
        return PreconditioningRules(
            applicability=applicability, electrical_tests=electrical, material=material
        )

    # --- tables ----------------------------------------------------------------------

    def impulse_selection_tables(self) -> ImpulseSelectionTables | None:
        resolved = {
            pair: self._table_pair(
                f"{ids.TEST_IMPULSE_SELECTION}.{pair}",
                row_axis_ids=IMPULSE_SELECTION_ROW_AXES,
                column_axis_id=_IMPULSE_SELECTION_COLUMN_AXIS,
            )
            for pair in IMPULSE_SELECTION_PAIRS
        }
        if any(item is None for item in resolved.values()):
            return None
        return ImpulseSelectionTables.model_validate(resolved)

    def dielectric_tables(self, base_id: str, *, row_axis_id: str) -> DielectricValueTables | None:
        # Both forms read the same row axis here: an AC and a DC column state two values for
        # one band, rather than two bands.
        row_axis_ids: Mapping[VoltageForm, str] = {form: row_axis_id for form in VOLTAGE_FORMS}
        resolved = {
            purpose: self._table_pair(
                f"{base_id}.{purpose}",
                row_axis_ids=row_axis_ids,
                column_axis_id=_DIELECTRIC_COLUMN_AXIS,
            )
            for purpose in DIELECTRIC_PURPOSES
        }
        if any(item is None for item in resolved.values()):
            return None
        return DielectricValueTables.model_validate(resolved)

    def _table_pair(
        self,
        base_id: str,
        *,
        row_axis_ids: Mapping[VoltageForm, str],
        column_axis_id: str,
    ) -> VoltageTablePair | None:
        resolved = {
            form: self._table(
                f"{base_id}.{form}",
                row_axis_id=row_axis_ids[form],
                column_axis_id=column_axis_id,
            )
            for form in VOLTAGE_FORMS
        }
        if resolved["ac"] is None or resolved["dc"] is None:
            return None
        return VoltageTablePair(ac=resolved["ac"], dc=resolved["dc"])

    def _table(self, table_id: str, *, row_axis_id: str, column_axis_id: str) -> Table | None:
        table = self._present(table_id, self._package.tables, "lookup table")
        if table is None:
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
        return table

    # --- curves ----------------------------------------------------------------------

    def curve(self, rule_id: str) -> PiecewiseCurveRule | None:
        return self._present(rule_id, self._package.curves, "curve rule")

    # --- shared ----------------------------------------------------------------------

    def _present[RuleT: (DecisionRule, ProcedureRule, Table, PiecewiseCurveRule)](
        self, rule_id: str, candidates: tuple[RuleT, ...], kind: str
    ) -> RuleT | None:
        rule = next((item for item in candidates if item.id == rule_id), None)
        if rule is None:
            self.blocks.append(
                VerificationRuleBlock(
                    code=VerificationRuleBlockCode.RULE_MISSING,
                    semantic_rule_id=rule_id,
                    message=f"The active package carries no {rule_id} {kind}.",
                )
            )
            return None
        if not self._same_edition(rule.source):
            self._wrong_edition(rule_id, rule.source)
            return None
        return rule

    def _same_edition(self, source: SourceReference) -> bool:
        return source.standard == STANDARD and source.edition == EDITION

    def _wrong_edition(self, rule_id: str, source: SourceReference) -> None:
        self.blocks.append(
            VerificationRuleBlock(
                code=VerificationRuleBlockCode.WRONG_EDITION,
                semantic_rule_id=rule_id,
                message=(
                    f"The active package's {rule_id} comes from {source.standard} "
                    f"{source.edition}, not {STANDARD} {EDITION}."
                ),
            )
        )

    def _shape(self, rule_id: str, detail: str) -> None:
        self.blocks.append(
            VerificationRuleBlock(
                code=VerificationRuleBlockCode.UNEXPECTED_SHAPE,
                semantic_rule_id=rule_id,
                message=f"The active package's {rule_id} {detail}.",
            )
        )


__all__ = [
    "DIELECTRIC_PURPOSES",
    "FOIL_APPLICABILITY_ROUTE",
    "IMPULSE_PROCEDURE_VARIANTS",
    "IMPULSE_SELECTION_PAIRS",
    "IMPULSE_SELECTION_ROW_AXES",
    "PACKAGE_CLASSIFICATIONS",
    "PARTIAL_DISCHARGE_APPLICABILITY_ROUTE",
    "PRECONDITIONING_APPLICABILITY_ROUTE",
    "PRECONDITIONING_ELECTRICAL_ROUTE",
    "PRECONDITIONING_MATERIAL_ROUTE",
    "READ_SEMANTIC_IDS",
    "RULES_READ_ELSEWHERE",
    "VOLTAGE_FORMS",
    "DielectricValueTables",
    "GatedProcedure",
    "ImpulseProcedureRules",
    "ImpulseSelectionTables",
    "PreconditioningRules",
    "VerificationRuleBlock",
    "VerificationRuleBlockCode",
    "VerificationRuleSet",
    "VerificationRulesUnavailable",
    "VoltageForm",
    "VoltageTablePair",
    "classifications_of",
    "read_verification_rules",
    "verification_rule_blocks",
]
