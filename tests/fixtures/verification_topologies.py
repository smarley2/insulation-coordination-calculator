"""A project and a rule package shaped for the dielectric verification planning tests.

Every name, identifier, band boundary and cell value here is invented for this repository.
Nothing reproduces a value, a heading, a note or any wording from any standard; what is
faithful is the *shape* the real projections produce.

Two things the existing fixtures do not offer are built here.

:func:`verification_topology` puts **two circuits inside one galvanic domain**, which
``tests.fixtures.supply_topologies`` deliberately does not: it gives one circuit per domain,
which is enough for a transfer and not enough for a connected live-part group. Grouping is what
makes deduplication mean anything, so a fixture without it cannot exercise it. It also carries
an accessible conductive part alongside the PE-bonded enclosure and the insulating cover, so
all four test topologies are reachable from one project.

:func:`single_column_dielectric_package` narrows the synthetic verification package's
dielectric routes to **one data column each**, which is what the real recipe projects: each
route takes the axis column plus one test-voltage column. The shared synthetic fixture states
two, so a route read from it is correctly refused - the package's column labels name the source
column they came from and say nothing about which one a test uses. Both shapes are needed: one
to plan from and one to be refused.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID

from insulation_coordination.calculation.verification_rules import (
    PRECONDITIONING_APPLICABILITY_ROUTE,
    PROTECTION_REQUIREMENT_OUTPUT,
)
from insulation_coordination.domain.dvc import DVC_INPUT, PROTECTION_TARGET_DIMENSIONS
from insulation_coordination.domain.enums import (
    BarrierVerificationStatus,
    CircuitSourceRelationship,
    ConnectionExposure,
    ConstructionType,
    DecisiveVoltageClass,
    FieldCondition,
    InsulationType,
    NetClassType,
    ReviewState,
    VerificationMethod,
)
from insulation_coordination.domain.project import (
    NetClass,
    PairCase,
    PairVoltage,
    PairVoltages,
    Project,
    ProjectDefaults,
    ProjectMetadata,
)
from insulation_coordination.domain.rules import (
    DecisionInput,
    DecisionOutput,
    DecisionRow,
    DecisionRule,
    DecisionValue,
    Matcher,
    RulePackage,
    SourceReference,
    Table,
    TableAxis,
    TableCell,
)
from insulation_coordination.domain.supply import (
    DeclaredSystemVoltage,
    EarthingArrangement,
    InputTopology,
    OvervoltageCategory,
    PhaseSystem,
    SupplyConfiguration,
    SupplyKind,
)
from insulation_coordination.domain.topology import GalvanicBarrier, GalvanicDomain
from insulation_coordination.domain.verification import SolidInsulationTestData
from insulation_coordination.project.pairs import canonical_pair_key, reconcile_pairs
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.iec62477_2022.inventory import EDITION, STANDARD
from tests.fixtures.synthetic_rules import (
    merged_rule_package,
    synthetic_reinforced_treatments,
    synthetic_requirement_table,
    synthetic_supply_rule_package,
    synthetic_verification_rule_package,
)

#: The project's nets. Two circuits share ``PRIMARY``; ``SECONDARY`` holds the third, behind a
#: verified barrier, so an adjacent-circuit pair crosses isolation.
PRIMARY = UUID(int=401)
SECONDARY = UUID(int=402)
LIVE_A = UUID(int=411)
LIVE_B = UUID(int=412)
LIVE_C = UUID(int=413)
ENCLOSURE = UUID(int=421)
TOUCHABLE = UUID(int=422)
COVER = UUID(int=423)
BARRIER = UUID(int=431)
SUPPLY = UUID(int=441)

#: The supply's declared system voltage. Inside the synthetic supply fixture's own band axis
#: and inside the dielectric row axis below, so one package answers both lookups. Both sets of
#: numbers are this repository's invention and only have to overlap.
SYSTEM_VOLTAGE_V = Decimal(33)

#: The dielectric routes' row axis. Chosen so ``SYSTEM_VOLTAGE_V`` lands strictly between two
#: bands, which is what makes a linear route and a banded route give different answers.
DIELECTRIC_ROW_BANDS: tuple[Decimal, ...] = (Decimal(10), Decimal(20), Decimal(40))

#: One invented cell value per route, so a test can tell which of the eight routes was read
#: from the number alone. The table family sets the ten-thousands, the purpose and voltage form
#: set the thousands, and the row index adds a hundred per band.
FAMILY_OFFSETS: dict[str, Decimal] = {
    ids.TEST_MAINS_DIELECTRIC_VALUES: Decimal(0),
    ids.TEST_NON_MAINS_DIELECTRIC_VALUES: Decimal(10000),
}
ROUTE_OFFSETS: dict[tuple[str, str], Decimal] = {
    ("routine_and_basic_type", "ac"): Decimal(1000),
    ("routine_and_basic_type", "dc"): Decimal(2000),
    ("enhanced_type", "ac"): Decimal(3000),
    ("enhanced_type", "dc"): Decimal(4000),
}


def dielectric_cell(base_id: str, purpose: str, form: str, band_index: int) -> Decimal:
    """The value this fixture puts in one route's band, so a test names it rather than a number."""

    return FAMILY_OFFSETS[base_id] + ROUTE_OFFSETS[purpose, form] + Decimal(100) * (band_index + 1)


def verification_topology(
    *,
    supply_configurations: tuple[SupplyConfiguration, ...] = (),
    insulation: InsulationType = InsulationType.BASIC,
    altitude_m: Decimal = Decimal(0),
    recurring_peak_v: Decimal | None = Decimal(25),
    frequency_hz: Decimal = Decimal(50),
) -> Project:
    """Three circuits over two domains, a PE-bonded part, a touchable part and a cover.

    ``LIVE_A`` and ``LIVE_B`` share ``PRIMARY``, so any test between one of them and a
    reference part covers both. Every pair carries dimensionable stresses, so nothing is
    excluded and nothing is blank.
    """

    domains = (
        GalvanicDomain(
            id=PRIMARY,
            name="Primary",
            is_direct_source_domain=True,
            review_state=ReviewState.USER_CONFIRMED,
        ),
        GalvanicDomain(id=SECONDARY, name="Secondary", review_state=ReviewState.USER_CONFIRMED),
    )
    nets = (
        _circuit(LIVE_A, "Live A", PRIMARY, CircuitSourceRelationship.MAINS_CONNECTED),
        _circuit(LIVE_B, "Live B", PRIMARY, CircuitSourceRelationship.INTERNALLY_GENERATED),
        _circuit(LIVE_C, "Live C", SECONDARY, CircuitSourceRelationship.INTERNALLY_GENERATED),
        _reference(ENCLOSURE, "Enclosure", NetClassType.PE_BONDED_CONDUCTIVE_PART),
        _reference(TOUCHABLE, "Handle", NetClassType.ACCESSIBLE_CONDUCTIVE_PART),
        _reference(COVER, "Cover", NetClassType.ACCESSIBLE_INSULATING_SURFACE),
    )
    pairs = tuple(_dimensionable(pair, recurring_peak_v) for pair in reconcile_pairs(nets, ()))
    return Project(
        id=UUID(int=400),
        metadata=ProjectMetadata(title="Verification topology example"),
        application_version="test",
        defaults=ProjectDefaults(
            frequency_hz=frequency_hz,
            insulation_type=insulation,
            field_condition=FieldCondition.INHOMOGENEOUS,
            altitude_m=altitude_m,
            pollution_degree=2,
            construction_type=ConstructionType.PRINTED_WIRING,
            cti_or_material_group="I",
        ),
        net_classes=nets,
        pairs=pairs,
        galvanic_domains=domains,
        galvanic_barriers=(
            GalvanicBarrier(
                id=BARRIER,
                domain_a_id=PRIMARY,
                domain_b_id=SECONDARY,
                status=BarrierVerificationStatus.VERIFIED_GALVANIC_ISOLATION,
                description="Primary to secondary",
                verification_method=VerificationMethod.TEST,
                evidence_reference="SYN-BARRIER-1",
            ),
        ),
        supply_configurations=supply_configurations,
    )


def mains_configuration(**overrides: object) -> SupplyConfiguration:
    """One enabled AC mains row, entirely this module's invention."""

    fields: dict[str, object] = {
        "id": SUPPLY,
        "enabled": True,
        "name": "Site supply",
        "supply_kind": SupplyKind.AC_MAINS,
        "nominal_voltage_v": SYSTEM_VOLTAGE_V,
        "phase_system": PhaseSystem.THREE_PHASE,
        "earthing_arrangement": EarthingArrangement.TN_STAR_POINT_EARTHED,
        "overvoltage_category": OvervoltageCategory.IV,
        "input_topology": InputTopology.DIRECT_INPUT,
        "declared_system_voltages": (
            DeclaredSystemVoltage(measure="phase_to_earth_rms", value_v=SYSTEM_VOLTAGE_V),
        ),
    }
    fields.update(overrides)
    return SupplyConfiguration(**fields)


def pair_between(project: Project, first: UUID, second: UUID) -> PairCase:
    key = canonical_pair_key(first, second)
    return next(pair for pair in project.pairs if pair.key == key)


def with_pair_fields(project: Project, pair_id: UUID | None = None, **fields: object) -> Project:
    """The same project with ``fields`` set on one pair, or on every pair when none is named.

    Pair ids are drawn per call by ``reconcile_pairs``, so a test that builds a project twice
    gets two different sets. Naming the pair by id keeps a test honest about which one it
    changed; leaving it out is how a whole-project state is set up in one line.
    """

    return project.model_copy(
        update={
            "pairs": tuple(
                pair.model_copy(update=fields) if pair_id in (None, pair.id) else pair
                for pair in project.pairs
            )
        }
    )


def declared_solid_insulation(**overrides: object) -> SolidInsulationTestData:
    """A fully declared single-layer construction, so a test states only what it is changing.

    Every figure is this module's own. ``present`` and ``material_pd_exempt`` are both
    answered, because the assessment under test treats an unanswered field and a negative
    answer as different things and a default that left one blank would hide that.
    """

    fields: dict[str, object] = {
        "present": True,
        "minimum_thickness_mm": Decimal("0.4"),
        "material_pd_exempt": False,
        "layer_count": 1,
        "material_reference": "SYN-MATERIAL-1",
    }
    fields.update(overrides)
    return SolidInsulationTestData(**fields)


#: The reviewed columns of this fixture's Table 3, as the five selector tokens each carries.
#: Four of them, because the plan narrows a lookup on the target and on whether an accessible
#: part is bonded to PE, and a fixture stating one column per target could not tell a narrowed
#: lookup from an unnarrowed one.
PROTECTION_COLUMNS: tuple[tuple[str, ...], ...] = (
    (
        "accessible_part",
        "connected_to_pe",
        "general_access",
        "ordinary_or_skilled",
        "not_applicable",
    ),
    (
        "accessible_part",
        "not_connected_to_pe",
        "general_access",
        "ordinary_or_skilled",
        "not_applicable",
    ),
    ("adjacent_circuit", "not_applicable", "not_applicable", "not_applicable", "dvc_b"),
    ("adjacent_circuit", "not_applicable", "not_applicable", "not_applicable", "dvc_c"),
)

#: What this fixture's Table 3 states in each cell, by class designation and column index.
#: Every one is invented here and none is read from anything. Three of them are placed to reach
#: a branch nothing else would:
#:
#: * DVC A-s states two different things about an accessible part depending on whether it is
#:   bonded, which is what a pair against an *insulating* surface runs into - nothing says
#:   whether that surface is bonded, both columns answer, and the plan refuses to pick one;
#: * the two adjacent-circuit columns disagree between a DVC B circuit facing a DVC C one and
#:   the same pair read the other way round, so the plan has to take the more demanding;
#: * no column carries an adjacent DVC A-s at all, which is the relationship a package simply
#:   does not answer for.
PROTECTION_CELLS: dict[tuple[str, int], str] = {
    ("dvc_as", 0): "none",
    ("dvc_as", 1): "basic_protection",
    ("dvc_as", 2): "none",
    ("dvc_as", 3): "none",
    ("dvc_b", 0): "basic_protection",
    ("dvc_b", 1): "basic_protection",
    ("dvc_b", 2): "basic_protection",
    ("dvc_b", 3): "enhanced_protection",
    ("dvc_c", 0): "enhanced_protection",
    ("dvc_c", 1): "enhanced_protection",
    ("dvc_c", 2): "basic_protection",
    ("dvc_c", 3): "enhanced_protection",
}


def with_protection_matrix(package: RulePackage) -> RulePackage:
    """The same package with a Table 3 shaped the way the verification adapter resolves it.

    The shared synthetic fixture carries Table 3 in its smallest legal shape, from when the
    adapter checked it for presence alone. Now that a plan asks it what protection is required,
    the adapter refuses a rule declaring a different input set - so a package a plan can be
    built from has to state the real dimensions. Replacing it here keeps that out of a fixture
    three other workstreams read, exactly as ``_located`` keeps the cell coordinates out of it.

    The replacement takes the placeholder's own source, so a package built for another edition
    stays in that edition and still blocks for the reason it was built to block for.
    """

    return package.model_copy(
        update={
            "decisions": tuple(
                _protection_matrix(decision.source)
                if decision.id == ids.DVC_PROTECTION_MATRIX
                else decision
                for decision in package.decisions
            )
        }
    )


def _protection_matrix(source: SourceReference) -> DecisionRule:
    """This fixture's Table 3: three classes against four reviewed protection targets."""

    designations = tuple(sorted({row for row, _ in PROTECTION_CELLS}))
    return DecisionRule(
        id=ids.DVC_PROTECTION_MATRIX,
        inputs=(
            DecisionInput(name=DVC_INPUT, kind="categorical", allowed_values=designations),
            *(
                DecisionInput(
                    name=name,
                    kind="categorical",
                    allowed_values=tuple(sorted({column[index] for column in PROTECTION_COLUMNS})),
                )
                for index, name in enumerate(PROTECTION_TARGET_DIMENSIONS)
            ),
        ),
        outputs=(
            DecisionOutput(
                name=PROTECTION_REQUIREMENT_OUTPUT,
                kind="categorical",
                allowed_values=("none", "basic_protection", "enhanced_protection"),
            ),
        ),
        rows=tuple(
            DecisionRow(
                matchers=(
                    Matcher(input=DVC_INPUT, op="equals", values=(designation,)),
                    *(
                        Matcher(input=name, op="equals", values=(PROTECTION_COLUMNS[index][at],))
                        for at, name in enumerate(PROTECTION_TARGET_DIMENSIONS)
                    ),
                ),
                values=(
                    DecisionValue(name=PROTECTION_REQUIREMENT_OUTPUT, categorical=requirement),
                ),
                source=source,
            )
            for (designation, index), requirement in PROTECTION_CELLS.items()
        ),
        # Not exhaustive, exactly as the real projection is: five structured target dimensions
        # multiply out far past the combinations any reviewed column carries.
        exhaustive=False,
        source=source,
    )


def single_column_dielectric_package(
    *,
    interpolation: str = "linear",
    partial_discharge_classifications: tuple[str, ...] = (),
) -> RulePackage:
    """The synthetic verification package with one-column dielectric routes.

    ``interpolation`` states what the routes permit, so a test can prove that a value between
    two bands is interpolated where the source allows it and read at the band above where it
    does not - without this application deciding either.

    ``partial_discharge_classifications`` states what the partial-discharge procedure says it
    is. The default is none, which is what the real projection produces: the classification is
    stated in a matrix that table does not carry, so the recipe declines to assert one. A test
    that needs the assessment to reach a settled answer supplies one, because a plan that does
    not know whether a test is a type or a sample test cannot schedule it either way.
    """

    package = with_protection_matrix(synthetic_verification_rule_package())
    replaced = {table.id: table for table in _dielectric_tables(interpolation)}
    # A reinforced pair is planned at the treated stress, so this package has to be able to
    # state the treatment and to carry the requirement whose axis a step would move along.
    source = package.tables[0].source
    return package.model_copy(
        update={
            "tables": (
                *(_located(replaced.get(table.id, table)) for table in package.tables),
                _located(synthetic_requirement_table(source)),
            ),
            "decisions": (
                *synthetic_reinforced_treatments(source),
                *(
                    _asked_by_purpose(decision)
                    if decision.id == PRECONDITIONING_APPLICABILITY_ROUTE
                    else decision
                    for decision in package.decisions
                ),
            ),
            "procedures": tuple(
                procedure.model_copy(update={"classifications": partial_discharge_classifications})
                if procedure.id == ids.TEST_PARTIAL_DISCHARGE
                else procedure
                for procedure in package.procedures
            ),
        }
    )


def _asked_by_purpose(gate: DecisionRule) -> DecisionRule:
    """The preconditioning gate with the purpose vocabulary the real projection declares.

    The shared synthetic fixture declares one invented purpose, which is enough to prove the
    adapter resolves the gate and not enough to ask it anything: a consumer supplies the
    package's name for the classification of the test being preconditioned, and a vocabulary
    that shares no name with one is a gate no test can reach.

    The three names here are the ones the adapter already translates in
    ``PACKAGE_CLASSIFICATIONS``, plus the third purpose the real gate carries that is not a
    classification at all. Nothing else about the gate changes: its rows still discriminate on
    the context alone, so widening the purpose only makes the electrical row reachable.
    """

    return gate.model_copy(
        update={
            "inputs": tuple(
                declared.model_copy(
                    update={"allowed_values": ("type_test", "sample_test", "acceptance_criteria")}
                )
                if declared.name == "test_purpose"
                else declared
                for declared in gate.inputs
            )
        }
    )


def _located(table: Table) -> Table:
    """The same table with each cell's locator naming its own row and column.

    A whole-package validation asks every cell where in its source it came from, and the
    shared synthetic fixture leaves that off because nothing ever wrote it through the
    archive. Adding the coordinates here keeps the merge writable without touching a fixture
    three other workstreams read.
    """

    return table.model_copy(
        update={
            "cells": tuple(
                cell.model_copy(
                    update={
                        "source": cell.source.model_copy(
                            update={
                                "row": table.row_axis.labels[cell.row],
                                "column": table.column_axis.labels[cell.column],
                            }
                        )
                    }
                )
                for cell in table.cells
            )
        }
    )


def verification_and_supply_package(
    path: Path,
    *,
    interpolation: str = "linear",
    partial_discharge_classifications: tuple[str, ...] = (),
) -> RulePackage:
    """One package answering the verification questions and the supply ones.

    Written and reloaded by ``merged_rule_package``, so it carries the SHA-256 identity a
    generated test id is derived from.
    """

    return merged_rule_package(
        single_column_dielectric_package(
            interpolation=interpolation,
            partial_discharge_classifications=partial_discharge_classifications,
        ),
        synthetic_supply_rule_package(),
        path=path,
    )


def _dielectric_tables(interpolation: str) -> tuple[Table, ...]:
    reference = SourceReference(
        document_id="synthetic-verification-source",
        standard=STANDARD,
        edition=EDITION,
        clause="synthetic-clause",
        table="synthetic-verification-table",
        note="Synthetic fixture only; contains no IEC numeric values.",
    )
    tables: list[Table] = []
    for base_id, row_axis_id in (
        (ids.TEST_MAINS_DIELECTRIC_VALUES, "system_voltage_v"),
        (ids.TEST_NON_MAINS_DIELECTRIC_VALUES, "working_voltage_recurring_peak_v"),
    ):
        for purpose in ("routine_and_basic_type", "enhanced_type"):
            for form in ("ac", "dc"):
                tables.append(
                    Table(
                        id=f"{base_id}.{purpose}.{form}",
                        unit="V",
                        row_axis=TableAxis(
                            id=row_axis_id,
                            unit="V",
                            values=DIELECTRIC_ROW_BANDS,
                            labels=tuple(f"band-{value}" for value in DIELECTRIC_ROW_BANDS),
                        ),
                        column_axis=TableAxis(
                            id="dielectric_test_column",
                            unit="1",
                            values=(Decimal(1),),
                            labels=("synthetic-test-voltage",),
                        ),
                        cells=tuple(
                            TableCell(
                                row=index,
                                column=0,
                                value=dielectric_cell(base_id, purpose, form, index),
                                unit="V",
                                source=reference,
                            )
                            for index in range(len(DIELECTRIC_ROW_BANDS))
                        ),
                        interpolation="linear" if interpolation == "linear" else "none",
                        source=reference,
                    )
                )
    return tuple(tables)


def _circuit(
    net_id: UUID, name: str, domain_id: UUID, source: CircuitSourceRelationship
) -> NetClass:
    return NetClass(
        id=net_id,
        name=name,
        net_type=NetClassType.CIRCUIT,
        source_relationship=source,
        connection_exposure=ConnectionExposure.INTERNAL_ONLY,
        decisive_voltage_class=DecisiveVoltageClass.DVC_B,
        galvanic_domain_id=domain_id,
        classification_review_state=ReviewState.USER_CONFIRMED,
    )


def _reference(net_id: UUID, name: str, net_type: NetClassType) -> NetClass:
    return NetClass(
        id=net_id,
        name=name,
        net_type=net_type,
        source_relationship=None,
        connection_exposure=None,
        decisive_voltage_class=None,
        galvanic_domain_id=None,
        classification_review_state=ReviewState.USER_CONFIRMED,
    )


def _dimensionable(pair: PairCase, recurring_peak_v: Decimal | None) -> PairCase:
    """Give every stress a value, so nothing is blank and no pair is excluded."""

    recurring = (
        PairVoltage.blank()
        if recurring_peak_v is None
        else PairVoltage.applicable(recurring_peak_v)
    )
    return pair.model_copy(
        update={
            "voltages": PairVoltages(
                long_term_rms_v=PairVoltage.applicable(Decimal(500)),
                steady_state_peak_v=PairVoltage.applicable(Decimal(300)),
                recurring_peak_v=recurring,
                temporary_overvoltage_peak_v=PairVoltage.applicable(Decimal(250)),
            )
        }
    )


__all__ = [
    "BARRIER",
    "COVER",
    "DIELECTRIC_ROW_BANDS",
    "ENCLOSURE",
    "FAMILY_OFFSETS",
    "LIVE_A",
    "LIVE_B",
    "LIVE_C",
    "PRIMARY",
    "PROTECTION_CELLS",
    "PROTECTION_COLUMNS",
    "ROUTE_OFFSETS",
    "SECONDARY",
    "SUPPLY",
    "SYSTEM_VOLTAGE_V",
    "TOUCHABLE",
    "declared_solid_insulation",
    "dielectric_cell",
    "mains_configuration",
    "pair_between",
    "single_column_dielectric_package",
    "verification_and_supply_package",
    "verification_topology",
    "with_pair_fields",
    "with_protection_matrix",
]
