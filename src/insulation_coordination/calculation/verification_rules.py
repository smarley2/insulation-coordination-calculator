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
from typing import Final, Literal

from insulation_coordination.calculation.clearance import CalculationError
from insulation_coordination.domain.dvc import DVC_INPUT, PROTECTION_TARGET_DIMENSIONS
from insulation_coordination.domain.frozen_model import FrozenModel
from insulation_coordination.domain.rules import (
    DecisionRule,
    PiecewiseCurveRule,
    ProcedureRule,
    RulePackage,
    SourceReference,
    Table,
)
from insulation_coordination.domain.verification import (
    TestApplicability,
    TestClassification,
    TestReferenceKind,
)
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

#: Table 27's two data columns, named by the insulation class each is headed by. The
#: overvoltage category names the *pair* of columns and the within-pair axis is the insulation
#: class, so these are what a consumer selects a column by - the same way a clearance branch is
#: selected in :mod:`~insulation_coordination.calculation.clearance`. They replaced labels that
#: named a physical position, which nothing could ask for; a route carrying the old labels is
#: refused here rather than read off a remembered index.
IMPULSE_SELECTION_COLUMN_LABELS: tuple[str, ...] = (
    "test_voltage_basic_or_supplementary_v",
    "test_voltage_double_or_reinforced_v",
)
BASIC_OR_SUPPLEMENTARY_COLUMN, DOUBLE_OR_REINFORCED_COLUMN = IMPULSE_SELECTION_COLUMN_LABELS


def dielectric_column_label(purpose: str, form: VoltageForm) -> str:
    """The label the package gives the one data column of one dielectric route.

    A dielectric route carries a single data column because the purpose and the voltage form
    are already in its own identifier, so nothing selects between columns here. It is still
    read by its label rather than by its position: a route that acquired a second column would
    otherwise be read at whichever one happened to come first.
    """

    return f"test_voltage_{purpose}_{form}_v"


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

#: The identifiers this adapter resolves, as base identifiers rather than their routes: the
#: thirteen issue #37 names as its rule dependency, and the four the body of clause 5.2.3.4
#: was given once it turned out that nothing in the package stated the test its two value
#: tables belong to.
READ_SEMANTIC_IDS: frozenset[str] = frozenset(
    {
        ids.TEST_DIELECTRIC_DISCONNECTION,
        ids.TEST_DIELECTRIC_TOPOLOGY_SELECTION,
        ids.TEST_DIELECTRIC_APPLICATION_DURATION,
        ids.TEST_DIELECTRIC_ACCEPTANCE,
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

#: The same translation the other way, for the one gate that takes a classification as an
#: *input* rather than declaring one. Derived rather than written out again, so the two
#: directions cannot come to disagree about what a classification is called.
CLASSIFICATION_NAMES: Mapping[TestClassification, str] = {
    classification: name for name, classification in PACKAGE_CLASSIFICATIONS.items()
}

# The names each gated decision is asked and read by. Public, unlike the shape sets below,
# because the assessments that ask them must not carry a package's vocabulary of their own: a
# name written in two modules is a name one of them can get wrong, and this is the module whose
# job is knowing it. The shape checks are built from exactly these, so a package that renames
# one is refused here rather than quietly answering nothing at a call site.
PROTECTION_REQUIREMENT_OUTPUT: Final = "protection_requirement"
PARTIAL_DISCHARGE_GATE_INPUT: Final = "partial_discharge_test_voltage_declared"
PARTIAL_DISCHARGE_GATE_OUTPUT: Final = "partial_discharge_test"
FOIL_GATE_INPUT: Final = "non_conductive_accessible_surface_present"
FOIL_WRAP_OUTPUT: Final = "foil_wrap_required"
FOIL_SUBSTITUTION_OUTPUT: Final = "permitted_classification_substitution"
PRECONDITIONING_CONTEXT_INPUT: Final = "test_context"
PRECONDITIONING_PURPOSE_INPUT: Final = "test_purpose"
PRECONDITIONING_REQUIRED_OUTPUT: Final = "preconditioning_required"
PRECONDITIONING_ROUTE_OUTPUT: Final = "preconditioning_procedure_rule_id"
EXEMPTION_OUTPUT: Final = "assembled_routine_test_exempt"

# --- the body of the AC or DC voltage test ---------------------------------------------
#
# The five inputs the topology selection is asked by and the two outputs it answers with. A
# consumer supplies all five: the evaluator answers ``input_required`` for any declared input a
# caller omits, so a question asked with four of them is not a question at all.
DIELECTRIC_REFERENCE_INPUT: Final = "reference_kind"
DIELECTRIC_CLASSIFICATION_INPUT: Final = "test_classification"
DIELECTRIC_DVC_AS_INPUT: Final = "circuit_under_test_is_dvc_as"
DIELECTRIC_BONDED_INPUT: Final = "circuit_connected_to_conductive_accessible_parts"
DIELECTRIC_ENHANCED_INPUT: Final = "enhanced_protection"
DIELECTRIC_COLUMN_OUTPUT: Final = "dielectric_column"
DIELECTRIC_ROW_AXIS_OUTPUT: Final = "row_axis_circuit"
#: The sentinel both output vocabularies carry for an application the source excludes. Not a
#: third output: a row forced to name a column it does not read would state a column nobody
#: asked for beside an exclusion.
DIELECTRIC_NOT_APPLICABLE: Final = "not_applicable"
#: Whose voltage keys the row. Every application but one is keyed on the circuit under test.
DIELECTRIC_ROW_CIRCUIT_UNDER_TEST: Final = "circuit_under_test"
DIELECTRIC_ROW_HIGHER_VOLTAGE_CIRCUIT: Final = "higher_voltage_circuit"

#: How this application's topology relationships read as the selection rule's own reference
#: vocabulary. Two of them answer to one value: a conductive accessible part that is not bonded
#: to earth and an insulating surface reached through conductive foil are one case as far as
#: the selection is concerned, and they differ only in the preparation the foil adds.
#:
#: :attr:`~insulation_coordination.domain.verification.TestReferenceKind.WITHIN_CIRCUIT` is
#: deliberately absent. The subclause enumerates the references an application is made
#: *against*, and a test inside one circuit is not among them - so the rule cannot be asked
#: about it, and a consumer reports that rather than picking the nearest value.
DIELECTRIC_REFERENCE_KINDS: Mapping[TestReferenceKind, str] = {
    TestReferenceKind.PE_BONDED_ACCESSIBLE_PART: "earthed_conductive_accessible_part",
    TestReferenceKind.ACCESSIBLE_CONDUCTIVE_PART: (
        "unearthed_or_non_conductive_accessible_surface"
    ),
    TestReferenceKind.ACCESSIBLE_INSULATING_SURFACE_FOIL: (
        "unearthed_or_non_conductive_accessible_surface"
    ),
    TestReferenceKind.ADJACENT_CIRCUIT: "adjacent_circuit",
    TestReferenceKind.DVC_AS_ADJACENT_CIRCUIT: "dvc_as_adjacent_circuit",
}

#: The one observation the acceptance criterion takes, and the one thing it settles.
DIELECTRIC_ACCEPTANCE_INPUT: Final = "electric_breakdown_observed"
DIELECTRIC_ACCEPTANCE_OUTPUT: Final = "voltage_test_passed"
#: The exemption's conditions in the order the source states them, which is the order a
#: decision trace reports them in. A set would lose that order, and a reviewer reading which
#: condition is missing reads it against the sequence the source states.
EXEMPTION_CONDITION_INPUTS: Final[tuple[str, ...]] = (
    "sub_assembly_routine_test_performed",
    "assembly_shown_not_to_compromise_insulation",
    "assembled_type_test_passed",
)

#: What the partial-discharge gate's own outcome vocabulary means as an applicability. There is
#: no "not required" among them on purpose: the source states its exemptions in prose the gate
#: does not tabulate, so the rule can say a test is required or that an input is missing, and
#: nothing else. An outcome this mapping does not name is reported unresolved rather than
#: translated to the nearest thing it resembles.
PARTIAL_DISCHARGE_OUTCOMES: Mapping[str, TestApplicability] = {
    "required": TestApplicability.REQUIRED,
    "engineering_input_required": TestApplicability.ENGINEERING_INPUT_REQUIRED,
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
_DIELECTRIC_DISCONNECTION_TEST_KIND = "dielectric_test_disconnection"
_DIELECTRIC_DURATION_TEST_KIND = "dielectric_voltage_application"

# The question each decision rule is resolved by: exactly the inputs this application supplies,
# and the outputs it reads. The input set is compared for equality rather than containment
# because the evaluator answers ``input_required`` for any declared input a caller omits - a
# package declaring one more input than this application knows about cannot be asked anything
# at all, and saying so is better than every query silently returning nothing. The output set
# is compared for containment: an output nothing here reads is harmless.
# Table 3's question, stated in the dimensions the DVC guidance service already resolves it
# by rather than in a second list of names. A plan asks the same rule the same way that page
# does, so the requirement it compares an implementation against is the one a reader is shown.
_PROTECTION_MATRIX_INPUTS = frozenset({DVC_INPUT, *PROTECTION_TARGET_DIMENSIONS})
_PROTECTION_MATRIX_OUTPUTS = frozenset({PROTECTION_REQUIREMENT_OUTPUT})

_PARTIAL_DISCHARGE_GATE_INPUTS = frozenset({PARTIAL_DISCHARGE_GATE_INPUT})
_PARTIAL_DISCHARGE_GATE_OUTPUTS = frozenset({PARTIAL_DISCHARGE_GATE_OUTPUT})

_FOIL_GATE_INPUTS = frozenset({FOIL_GATE_INPUT})
_FOIL_GATE_OUTPUTS = frozenset({FOIL_WRAP_OUTPUT, FOIL_SUBSTITUTION_OUTPUT})

_PRECONDITIONING_GATE_INPUTS = frozenset(
    {PRECONDITIONING_CONTEXT_INPUT, PRECONDITIONING_PURPOSE_INPUT}
)
_PRECONDITIONING_GATE_OUTPUTS = frozenset(
    {PRECONDITIONING_REQUIRED_OUTPUT, PRECONDITIONING_ROUTE_OUTPUT}
)

_EXEMPTION_INPUTS = frozenset(EXEMPTION_CONDITION_INPUTS)
_EXEMPTION_OUTPUTS = frozenset({EXEMPTION_OUTPUT})

_DIELECTRIC_SELECTION_INPUTS = frozenset(
    {
        DIELECTRIC_REFERENCE_INPUT,
        DIELECTRIC_CLASSIFICATION_INPUT,
        DIELECTRIC_DVC_AS_INPUT,
        DIELECTRIC_BONDED_INPUT,
        DIELECTRIC_ENHANCED_INPUT,
    }
)
_DIELECTRIC_SELECTION_OUTPUTS = frozenset({DIELECTRIC_COLUMN_OUTPUT, DIELECTRIC_ROW_AXIS_OUTPUT})

_DIELECTRIC_ACCEPTANCE_INPUTS = frozenset({DIELECTRIC_ACCEPTANCE_INPUT})
_DIELECTRIC_ACCEPTANCE_OUTPUTS = frozenset({DIELECTRIC_ACCEPTANCE_OUTPUT})

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
    #: The four rules the body of clause 5.2.3.4 states around its two value tables: what is
    #: disconnected before the voltage is applied, which column and row side an application
    #: reads, how long the voltage is held, and what settles the result.
    dielectric_disconnection: ProcedureRule
    dielectric_topology_selection: DecisionRule
    dielectric_application_duration: ProcedureRule
    dielectric_acceptance: DecisionRule
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
        "dvc_protection_matrix": reader.decision(
            ids.DVC_PROTECTION_MATRIX,
            inputs=_PROTECTION_MATRIX_INPUTS,
            outputs=_PROTECTION_MATRIX_OUTPUTS,
        ),
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
        "dielectric_disconnection": reader.procedure(
            ids.TEST_DIELECTRIC_DISCONNECTION, test_kind=_DIELECTRIC_DISCONNECTION_TEST_KIND
        ),
        "dielectric_topology_selection": reader.decision(
            ids.TEST_DIELECTRIC_TOPOLOGY_SELECTION,
            inputs=_DIELECTRIC_SELECTION_INPUTS,
            outputs=_DIELECTRIC_SELECTION_OUTPUTS,
        ),
        "dielectric_application_duration": reader.procedure(
            ids.TEST_DIELECTRIC_APPLICATION_DURATION,
            test_kind=_DIELECTRIC_DURATION_TEST_KIND,
            states_duration=True,
        ),
        "dielectric_acceptance": reader.decision(
            ids.TEST_DIELECTRIC_ACCEPTANCE,
            inputs=_DIELECTRIC_ACCEPTANCE_INPUTS,
            outputs=_DIELECTRIC_ACCEPTANCE_OUTPUTS,
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

        Table 2's input and output contract is owned by
        :class:`~insulation_coordination.domain.dvc.DvcGuidanceService`, which already resolves
        it against its reviewed selector dimensions, and no verification question asks it
        anything: a plan reads its working voltages from the evidence library and its impulse
        from issue #36's derivation. Asserting an input set nothing here supplies would block a
        good package over a question nobody asks. What the plan needs from this seam is the
        guarantee that the rule is present and from the right edition.

        Table 3 is no longer resolved this way. A plan asks it what protection the package
        requires, so it is resolved by :meth:`decision` against the same dimensions the
        guidance service reads it by - a rule shaped differently answers ``input_required`` to
        every question, and a plan cannot report that as a requirement.
        """

        return self._present(rule_id, self._package.decisions, "decision rule")

    # --- procedures ------------------------------------------------------------------

    def procedure(
        self, rule_id: str, *, test_kind: str, states_duration: bool = False
    ) -> ProcedureRule | None:
        rule = self._present(rule_id, self._package.procedures, "procedure rule")
        if rule is None:
            return None
        if rule.test_kind != test_kind:
            self._shape(rule_id, f"performs {rule.test_kind!r} rather than {test_kind!r}")
            return None
        if states_duration and not rule.duration:
            # The one procedure resolved *for* its duration. A rule of this identifier that
            # states none answers nothing a consumer asked it, and reporting that on every
            # planned row instead would say the schedule is incomplete when the package is.
            self._shape(rule_id, "states no duration for the test it is resolved to state")
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
                column_labels=dict.fromkeys(VOLTAGE_FORMS, IMPULSE_SELECTION_COLUMN_LABELS),
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
                column_labels={
                    form: (dielectric_column_label(purpose, form),) for form in VOLTAGE_FORMS
                },
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
        column_labels: Mapping[VoltageForm, tuple[str, ...]] | None = None,
    ) -> VoltageTablePair | None:
        resolved = {
            form: self._table(
                f"{base_id}.{form}",
                row_axis_id=row_axis_ids[form],
                column_axis_id=column_axis_id,
                column_labels=() if column_labels is None else column_labels[form],
            )
            for form in VOLTAGE_FORMS
        }
        if resolved["ac"] is None or resolved["dc"] is None:
            return None
        return VoltageTablePair(ac=resolved["ac"], dc=resolved["dc"])

    def _table(
        self,
        table_id: str,
        *,
        row_axis_id: str,
        column_axis_id: str,
        column_labels: tuple[str, ...] = (),
    ) -> Table | None:
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
        # A route whose columns a consumer selects between has to name them. Checked here so a
        # plan resolves a column the way a clearance branch is resolved - by the label the
        # package carries - instead of remembering a position, which is what the labels these
        # names replaced amounted to.
        missing = sorted(set(column_labels) - set(table.column_axis.labels))
        if missing:
            self._shape(table_id, f"labels no column {missing}")
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
    "BASIC_OR_SUPPLEMENTARY_COLUMN",
    "CLASSIFICATION_NAMES",
    "DIELECTRIC_ACCEPTANCE_INPUT",
    "DIELECTRIC_ACCEPTANCE_OUTPUT",
    "DIELECTRIC_BONDED_INPUT",
    "DIELECTRIC_CLASSIFICATION_INPUT",
    "DIELECTRIC_COLUMN_OUTPUT",
    "DIELECTRIC_DVC_AS_INPUT",
    "DIELECTRIC_ENHANCED_INPUT",
    "DIELECTRIC_NOT_APPLICABLE",
    "DIELECTRIC_PURPOSES",
    "DIELECTRIC_REFERENCE_INPUT",
    "DIELECTRIC_REFERENCE_KINDS",
    "DIELECTRIC_ROW_AXIS_OUTPUT",
    "DIELECTRIC_ROW_CIRCUIT_UNDER_TEST",
    "DIELECTRIC_ROW_HIGHER_VOLTAGE_CIRCUIT",
    "DOUBLE_OR_REINFORCED_COLUMN",
    "EXEMPTION_CONDITION_INPUTS",
    "EXEMPTION_OUTPUT",
    "FOIL_APPLICABILITY_ROUTE",
    "FOIL_GATE_INPUT",
    "FOIL_SUBSTITUTION_OUTPUT",
    "FOIL_WRAP_OUTPUT",
    "IMPULSE_PROCEDURE_VARIANTS",
    "IMPULSE_SELECTION_COLUMN_LABELS",
    "IMPULSE_SELECTION_PAIRS",
    "IMPULSE_SELECTION_ROW_AXES",
    "PACKAGE_CLASSIFICATIONS",
    "PARTIAL_DISCHARGE_APPLICABILITY_ROUTE",
    "PARTIAL_DISCHARGE_GATE_INPUT",
    "PARTIAL_DISCHARGE_GATE_OUTPUT",
    "PARTIAL_DISCHARGE_OUTCOMES",
    "PRECONDITIONING_APPLICABILITY_ROUTE",
    "PRECONDITIONING_CONTEXT_INPUT",
    "PRECONDITIONING_ELECTRICAL_ROUTE",
    "PRECONDITIONING_MATERIAL_ROUTE",
    "PRECONDITIONING_PURPOSE_INPUT",
    "PRECONDITIONING_REQUIRED_OUTPUT",
    "PRECONDITIONING_ROUTE_OUTPUT",
    "PROTECTION_REQUIREMENT_OUTPUT",
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
    "dielectric_column_label",
    "read_verification_rules",
    "verification_rule_blocks",
]
