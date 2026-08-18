from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from insulation_coordination.domain.dvc import PROTECTION_TARGET_DIMENSIONS
from insulation_coordination.domain.rules import (
    RULE_SCHEMA_VERSION,
    Add,
    ApprovalRecord,
    Compare,
    CompatibilityMapping,
    CurveAxis,
    CurvePoint,
    CurveSegment,
    DecisionInput,
    DecisionOutput,
    DecisionRow,
    DecisionRule,
    DecisionValue,
    Divide,
    FaultTimeVoltageSelector,
    FaultTimeVoltageVariant,
    Formula,
    GuidanceRule,
    LinearInterpolate,
    Literal,
    Lookup,
    Manifest,
    Matcher,
    Maximum,
    Minimum,
    Multiply,
    Parameter,
    ParameterSet,
    PiecewiseCurveRule,
    ProcedureRule,
    ProcedureStep,
    Round,
    RulePackage,
    Select,
    SourceDocument,
    SourceReference,
    SupportedRange,
    Table,
    TableAxis,
    TableCell,
    TableSelect,
    Variable,
)
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.iec62477_2022.inventory import EDITION, STANDARD

#: Coordinates of the invented requirement axis a reinforced impulse steps along, in volts.
#: Repeated digits, chosen so no source series can be read out of them.
SYNTHETIC_REQUIREMENT_LEVELS_V: tuple[Decimal, ...] = tuple(
    map(Decimal, ("110", "220", "1100", "2200"))
)

#: An obviously invented treatment factor: a whole number nothing any document states. What the
#: licensed clauses state reaches the runtime from the approved package, never from here.
SYNTHETIC_REINFORCED_FACTOR = Decimal(3)

#: The vocabularies the reinforced treatment routes declare, mirroring the projector's.
_INSULATION_CLASSES = ("functional", "basic", "supplementary", "double", "reinforced")
_TREATED_QUANTITIES = (
    "impulse_withstand_voltage",
    "temporary_overvoltage_peak",
    "working_voltage_peak",
    "basic_insulation_requirement",
)


def synthetic_requirement_table(source: SourceReference) -> Table:
    """The requirement a reinforced clearance treatment defers to, as an axis to step along.

    Only its row axis is load bearing for the treatment: the cells exist because a table has
    to have some, and are invented like every other number in this module.
    """

    return Table(
        id=ids.CLEARANCE_REQUIREMENTS,
        unit="mm",
        row_axis=TableAxis(
            id="impulse_withstand_voltage_v",
            unit="V",
            values=SYNTHETIC_REQUIREMENT_LEVELS_V,
            labels=tuple(str(value) for value in SYNTHETIC_REQUIREMENT_LEVELS_V),
        ),
        column_axis=TableAxis(
            id="pollution_degree",
            unit="1",
            values=(Decimal(1), Decimal(2)),
            labels=("pollution_degree_1", "pollution_degree_2"),
        ),
        cells=tuple(
            TableCell(
                row=row,
                column=column,
                value=Decimal(row + 1) + Decimal(column + 1) / Decimal(10),
                unit="mm",
                source=source,
            )
            for row in range(len(SYNTHETIC_REQUIREMENT_LEVELS_V))
            for column in range(2)
        ),
        interpolation="none",
        source=source,
    )


def synthetic_reinforced_treatments(source: SourceReference) -> tuple[DecisionRule, ...]:
    """The two reinforced treatment routes, in the shape the real projector emits.

    Shape only. Every row here states a multiplication by the invented factor above, including
    the impulse one: the mode a source states is not this module's to reproduce, and a suite
    that wanted the stepping branch asks for it explicitly through
    :func:`with_stepped_reinforced_impulse`.

    The clearance route states the axis its treatment defers to and the creepage route does
    not, which is the one structural difference between them and the reason a consumer can
    follow a step without naming an axis itself.
    """

    def rule(rule_id: str, *, states_axis: bool, quantities: tuple[str, ...]) -> DecisionRule:
        return DecisionRule(
            id=rule_id,
            inputs=(
                DecisionInput(
                    name="insulation_class",
                    kind="categorical",
                    allowed_values=_INSULATION_CLASSES,
                ),
                DecisionInput(
                    name="treated_quantity",
                    kind="categorical",
                    allowed_values=_TREATED_QUANTITIES,
                ),
            ),
            outputs=(
                DecisionOutput(
                    name="treatment_mode",
                    kind="categorical",
                    allowed_values=("multiply", "next_level_in_requirement_axis"),
                ),
                DecisionOutput(name="treatment_multiplier", kind="numeric"),
                *(
                    (DecisionOutput(name="preferred_level_axis", kind="reference"),)
                    if states_axis
                    else ()
                ),
            ),
            rows=tuple(
                DecisionRow(
                    matchers=(
                        Matcher(input="insulation_class", op="equals", values=("reinforced",)),
                        Matcher(input="treated_quantity", op="equals", values=(quantity,)),
                    ),
                    values=(
                        DecisionValue(name="treatment_mode", categorical="multiply"),
                        DecisionValue(
                            name="treatment_multiplier", numeric=SYNTHETIC_REINFORCED_FACTOR
                        ),
                        *(
                            (
                                DecisionValue(
                                    name="preferred_level_axis",
                                    reference=ids.CLEARANCE_REQUIREMENTS,
                                ),
                            )
                            if states_axis
                            else ()
                        ),
                    ),
                    source=source,
                )
                for quantity in quantities
            ),
            # A class or a quantity no row covers reaches none, rather than being told that
            # nothing needs doing to it.
            exhaustive=False,
            source=source,
        )

    return (
        rule(
            ids.CLEARANCE_REINFORCED_TREATMENT,
            states_axis=True,
            quantities=_TREATED_QUANTITIES[:3],
        ),
        rule(
            ids.CREEPAGE_REINFORCED_TREATMENT,
            states_axis=False,
            quantities=_TREATED_QUANTITIES[3:],
        ),
    )


def with_stepped_reinforced_impulse(package: RulePackage) -> RulePackage:
    """``package`` with its reinforced impulse treatment restated as a step along the axis.

    The other branch of the family, for the tests that are about it. Nothing else changes, so
    a test can compare the two readings of one package.
    """

    def stepped(rule: DecisionRule) -> DecisionRule:
        if rule.id != ids.CLEARANCE_REINFORCED_TREATMENT:
            return rule
        rows = tuple(
            row.model_copy(
                update={
                    "values": tuple(
                        value.model_copy(update={"categorical": "next_level_in_requirement_axis"})
                        if value.name == "treatment_mode"
                        else value.model_copy(update={"numeric": Decimal(1)})
                        if value.name == "treatment_multiplier"
                        else value
                        for value in row.values
                    )
                }
            )
            if any(
                matcher.input == "treated_quantity"
                and matcher.values == ("impulse_withstand_voltage",)
                for matcher in row.matchers
            )
            else row
            for row in rule.rows
        )
        return rule.model_copy(update={"rows": rows})

    return package.model_copy(
        update={
            "decisions": tuple(stepped(rule) for rule in package.decisions),
            "checksums": {},
            "package_sha256": None,
        }
    )


def claimed_standards(package: RulePackage) -> set[str]:
    """Every standard identity a package attributes its content to."""
    return {
        item.source.standard
        for group in (
            package.tables,
            package.formulas,
            package.mappings,
            package.decisions,
            package.procedures,
            package.guidance,
            package.curves,
        )
        for item in group
    } | {document.standard for document in package.manifest.source_documents}


def synthetic_rule_package() -> RulePackage:
    reference = SourceReference(
        document_id="synthetic-source",
        standard="SYNTHETIC-1",
        edition="1",
        clause="4.2",
        table="T-1",
        figure=None,
        row="synthetic row",
        column="synthetic column",
        note="Synthetic fixture only.",
    )
    table_range = SupportedRange(
        variable="voltage",
        minimum=Decimal(0),
        maximum=Decimal(20),
        unit="V",
        source=reference,
    )
    table = Table(
        id="synthetic-distance",
        unit="mm",
        row_axis=TableAxis(
            id="voltage",
            unit="V",
            values=(Decimal(0), Decimal(20)),
            labels=("voltage-0", "voltage-20"),
        ),
        column_axis=TableAxis(
            id="category",
            unit="1",
            values=(Decimal(1), Decimal(2)),
            labels=("category-1", "category-2"),
        ),
        cells=(
            TableCell(
                row=0,
                column=0,
                value=Decimal("1.00"),
                unit="mm",
                source=reference.model_copy(update={"row": "0", "column": "1"}),
            ),
            TableCell(
                row=0,
                column=1,
                value=Decimal("1.50"),
                unit="mm",
                source=reference.model_copy(update={"row": "0", "column": "2"}),
            ),
            TableCell(
                row=1,
                column=0,
                value=Decimal("2.00"),
                unit="mm",
                source=reference.model_copy(update={"row": "20", "column": "1"}),
            ),
            TableCell(
                row=1,
                column=1,
                value=Decimal("2.50"),
                unit="mm",
                source=reference.model_copy(update={"row": "20", "column": "2"}),
            ),
        ),
        supported_ranges=(table_range,),
        interpolation="linear",
        rounding_places=2,
        rounding_mode="ROUND_HALF_UP",
        source=reference,
    )
    expression = Select(
        condition=Compare(
            comparison="gt",
            left=Variable(name="voltage"),
            right=Literal(value=Decimal(10)),
        ),
        if_true=Round(
            value=Divide(
                numerator=Multiply(
                    operands=(
                        Variable(name="voltage"),
                        Literal(value=Decimal(2)),
                    )
                ),
                denominator=Literal(value=Decimal(4)),
            ),
            places=2,
            mode="ROUND_HALF_EVEN",
        ),
        if_false=Maximum(
            operands=(
                Minimum(
                    operands=(
                        Literal(value=Decimal(1)),
                        Literal(value=Decimal(2)),
                    )
                ),
                Add(
                    operands=(
                        Literal(value=Decimal(3)),
                        Lookup(
                            table_id="synthetic-distance",
                            row=Literal(value=Decimal(0)),
                            column=Literal(value=Decimal(1)),
                        ),
                    )
                ),
                LinearInterpolate(
                    table_id="synthetic-distance",
                    x=Variable(name="voltage"),
                    column=Literal(value=Decimal(1)),
                ),
            )
        ),
    )
    formula_range = SupportedRange(
        variable="voltage",
        minimum=Decimal(0),
        maximum=Decimal(20),
        unit="V",
        source=reference,
    )
    formula = Formula(
        id="synthetic-formula",
        expression=expression,
        unit="mm",
        parameter_sets=(
            ParameterSet(
                id="default",
                parameters=(
                    Parameter(
                        name="voltage",
                        unit="V",
                        minimum=Decimal(0),
                        maximum=Decimal(20),
                    ),
                ),
                source=reference,
            ),
        ),
        supported_ranges=(formula_range,),
        latex="d = f(U)",
        source=reference,
    )
    decision = DecisionRule(
        id="synthetic-decision",
        inputs=(
            DecisionInput(
                name="synthetic_category",
                kind="categorical",
                allowed_values=("alpha", "beta"),
            ),
        ),
        outputs=(
            DecisionOutput(
                name="synthetic_protection",
                kind="categorical",
                allowed_values=("basic", "enhanced"),
            ),
        ),
        rows=(
            DecisionRow(
                matchers=(Matcher(input="synthetic_category", op="equals", values=("alpha",)),),
                values=(DecisionValue(name="synthetic_protection", categorical="basic"),),
                source=reference,
            ),
            DecisionRow(
                matchers=(Matcher(input="synthetic_category", op="equals", values=("beta",)),),
                values=(DecisionValue(name="synthetic_protection", categorical="enhanced"),),
                source=reference,
            ),
        ),
        exhaustive=True,
        applicability="Synthetic fixture only.",
        source=reference,
    )
    procedure = ProcedureRule(
        id="synthetic-procedure",
        test_kind="synthetic-test",
        classifications=("type",),
        waveform="synthetic waveform",
        procedure_steps=(
            ProcedureStep(order=1, text="Synthetic preparation.", source=reference),
            ProcedureStep(order=2, text="Synthetic application.", source=reference),
        ),
        applicability_rule_id="synthetic-decision",
        source=reference,
    )
    guidance = GuidanceRule(
        id="synthetic-guidance",
        title="Synthetic guidance",
        summary="Synthetic summary, no IEC content.",
        warnings=("Synthetic warning.",),
        source=reference,
    )
    curve = PiecewiseCurveRule(
        id="synthetic-fault-time-voltage",
        variants=(
            FaultTimeVoltageVariant(
                id="synthetic-dc-dvc",
                selector=FaultTimeVoltageSelector(
                    subject="accessible_circuit",
                    voltage_basis="dc",
                    dvc_context="synthetic-dvc",
                    environment_context=None,
                ),
                x_axis=CurveAxis(
                    quantity_kind="fault-time",
                    unit="ms",
                    scale="log10",
                    minimum=Decimal(3),
                    maximum=Decimal(243),
                ),
                y_axis=CurveAxis(
                    quantity_kind="voltage-limit",
                    unit="V",
                    scale="log10",
                    minimum=Decimal(89),
                    maximum=Decimal(777),
                ),
                points=(
                    CurvePoint(x=Decimal(3), y=Decimal(777)),
                    CurvePoint(x=Decimal(27), y=Decimal(271)),
                    CurvePoint(x=Decimal(243), y=Decimal(89)),
                ),
                segments=(
                    CurveSegment(
                        start=0,
                        end=1,
                        segment_type="continuous",
                        interpolation="log_log",
                    ),
                    CurveSegment(
                        start=1,
                        end=2,
                        segment_type="continuous",
                        interpolation="log_log",
                    ),
                ),
                applicability="Synthetic fixture only.",
                source=reference,
                reviewed_artifact_sha256="b" * 64,
            ),
        ),
        source=reference,
    )
    return RulePackage(
        manifest=Manifest(
            schema_version=RULE_SCHEMA_VERSION,
            package_id="00000000-0000-0000-0000-000000000001",
            version="1.0",
            importer_version="test-1",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            source_documents=(
                SourceDocument(
                    id="synthetic-source",
                    standard="SYNTHETIC-1",
                    edition="1",
                    sha256="a" * 64,
                ),
            ),
            approved=True,
            compatible=True,
            approval_records=(
                ApprovalRecord(
                    action="approval",
                    actor="Synthetic Reviewer",
                    recorded_at=datetime(2026, 1, 2, tzinfo=UTC),
                    notes="Synthetic data reviewed.",
                ),
            ),
        ),
        tables=(table,),
        formulas=(formula,),
        mappings=(
            CompatibilityMapping(
                id="synthetic-compatibility",
                source_rule_id="synthetic-part-a",
                target_rule_id="synthetic-formula",
                approved=True,
                source=reference,
            ),
        ),
        decisions=(decision,),
        procedures=(procedure,),
        guidance=(guidance,),
        curves=(curve,),
    )


def synthetic_part1_rule_package() -> RulePackage:
    reference = SourceReference(
        document_id="synthetic-part-1-source",
        standard="SYNTHETIC-PART-1",
        edition="1",
        clause="synthetic",
        table="synthetic-distance",
        row="synthetic row",
        column="synthetic column",
        note="Visibly synthetic fixture only; contains no IEC numeric values.",
    )

    def distance_table(
        table_id: str,
        maximum_stress: Decimal,
        low_distance: str,
        high_distance: str,
    ) -> Table:
        return Table(
            id=table_id,
            unit="mm",
            row_axis=TableAxis(
                id="stress_v",
                unit="V",
                values=(Decimal(100), maximum_stress),
                labels=("stress-low", "stress-high"),
            ),
            column_axis=TableAxis(
                id="synthetic_branch",
                unit="1",
                values=(Decimal(1),),
                labels=("synthetic-branch",),
            ),
            cells=(
                TableCell(
                    row=0,
                    column=0,
                    value=Decimal(low_distance),
                    unit="mm",
                    source=reference.model_copy(update={"row": "low", "column": "1"}),
                ),
                TableCell(
                    row=1,
                    column=0,
                    value=Decimal(high_distance),
                    unit="mm",
                    source=reference.model_copy(update={"row": "high", "column": "1"}),
                ),
            ),
            supported_ranges=(
                SupportedRange(
                    variable="stress_v",
                    minimum=Decimal(100),
                    maximum=maximum_stress,
                    unit="V",
                    source=reference,
                ),
            ),
            interpolation="linear",
            rounding_places=2,
            rounding_mode="ROUND_HALF_UP",
            source=reference,
        )

    table_specs = (
        ("synthetic-clearance-functional-impulse", Decimal(1000), "0.50", "2.00"),
        ("synthetic-clearance-basic-impulse", Decimal(1000), "1.00", "3.00"),
        ("synthetic-clearance-reinforced-impulse", Decimal(1000), "2.00", "5.50"),
        ("synthetic-clearance-functional-periodic", Decimal(1000), "0.25", "1.50"),
        ("synthetic-clearance-basic-periodic", Decimal(1000), "0.50", "2.00"),
        ("synthetic-clearance-reinforced-periodic", Decimal(1000), "1.00", "4.00"),
        ("synthetic-creepage-functional", Decimal(500), "1.00", "3.00"),
        ("synthetic-creepage-basic", Decimal(500), "1.50", "4.00"),
        ("synthetic-creepage-reinforced", Decimal(500), "2.50", "8.00"),
    )
    tables = tuple(
        distance_table(table_id, maximum, low, high) for table_id, maximum, low, high in table_specs
    )
    formulas = tuple(
        Formula(
            id=f"{table.id}-formula",
            expression=LinearInterpolate(
                table_id=table.id,
                x=Variable(name="stress_v"),
            ),
            unit="mm",
            parameter_sets=(
                ParameterSet(
                    id="synthetic-default",
                    parameters=(
                        Parameter(
                            name="stress_v",
                            unit="V",
                            minimum=table.row_axis.values[0],
                            maximum=table.row_axis.values[-1],
                        ),
                    ),
                    source=reference,
                ),
            ),
            supported_ranges=table.supported_ranges,
            latex="d_{synthetic} = f(U_{synthetic})",
            applicability="Synthetic Part 1 route only.",
            source=reference,
        )
        for table in tables
    )
    route_specs = (
        (
            "functional_clearance_impulse",
            (
                "iec60664-1:5.2.4:functional_clearance:"
                "candidate=impulse:field=inhomogeneous:pollution={pollution}"
            ),
            "synthetic-clearance-functional-impulse-formula",
        ),
        (
            "basic_clearance_impulse",
            (
                "iec60664-1:5.2.5:basic_clearance:"
                "candidate=impulse:field=inhomogeneous:pollution={pollution}"
            ),
            "synthetic-clearance-basic-impulse-formula",
        ),
        (
            "reinforced_clearance_impulse",
            (
                "iec60664-1:5.2.5:reinforced_clearance:"
                "candidate=impulse:field=inhomogeneous:pollution={pollution}"
            ),
            "synthetic-clearance-reinforced-impulse-formula",
        ),
        (
            "functional_clearance_periodic",
            (
                "iec60664-1:5.2.4:functional_clearance:"
                "candidate=periodic:field=inhomogeneous:pollution={pollution}"
            ),
            "synthetic-clearance-functional-periodic-formula",
        ),
        (
            "basic_clearance_periodic",
            (
                "iec60664-1:5.2.5:basic_clearance:"
                "candidate=periodic:field=inhomogeneous:pollution={pollution}"
            ),
            "synthetic-clearance-basic-periodic-formula",
        ),
        (
            "reinforced_clearance_periodic",
            (
                "iec60664-1:5.2.5:reinforced_clearance:"
                "candidate=periodic:field=inhomogeneous:pollution={pollution}"
            ),
            "synthetic-clearance-reinforced-periodic-formula",
        ),
        (
            "functional_creepage",
            (
                "iec60664-1:5.3.4:functional_creepage:"
                "construction=other:pollution={pollution}:material=I"
            ),
            "synthetic-creepage-functional-formula",
        ),
        (
            "basic_creepage",
            "iec60664-1:5.3.5:basic_creepage:construction=other:pollution={pollution}:material=I",
            "synthetic-creepage-basic-formula",
        ),
        (
            "reinforced_creepage",
            (
                "iec60664-1:5.3.5:reinforced_creepage:"
                "construction=other:pollution={pollution}:material=I"
            ),
            "synthetic-creepage-reinforced-formula",
        ),
    )
    # Real packages carry every pollution degree; inner layers are dimensioned in
    # pollution degree 1, so the fixture routes both like the importer recipes do.
    mapping_specs = tuple(
        (
            mapping_id if pollution == 2 else f"{mapping_id}_pd{pollution}",
            source_rule_id.format(pollution=pollution),
            target_rule_id,
        )
        for pollution in (2, 1)
        for mapping_id, source_rule_id, target_rule_id in route_specs
    )
    return RulePackage(
        manifest=Manifest(
            schema_version=RULE_SCHEMA_VERSION,
            package_id="00000000-0000-0000-0000-000000000006",
            version="part1-synthetic-1",
            importer_version="test-1",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            source_documents=(
                SourceDocument(
                    id="synthetic-part-1-source",
                    standard="SYNTHETIC-PART-1",
                    edition="1",
                    sha256="b" * 64,
                ),
            ),
            approved=True,
            compatible=True,
            approval_records=(
                ApprovalRecord(
                    action="approval",
                    actor="Synthetic Reviewer",
                    recorded_at=datetime(2026, 1, 2, tzinfo=UTC),
                    notes="Synthetic Part 1 data reviewed.",
                ),
            ),
        ),
        tables=(*tables, synthetic_requirement_table(reference)),
        formulas=formulas,
        mappings=tuple(
            CompatibilityMapping(
                id=mapping_id,
                source_rule_id=source_rule_id,
                target_rule_id=target_rule_id,
                approved=True,
                source=reference,
            )
            for mapping_id, source_rule_id, target_rule_id in mapping_specs
        ),
        decisions=synthetic_reinforced_treatments(reference),
    )


def synthetic_hf_rule_package() -> RulePackage:
    base = synthetic_part1_rule_package()
    reference = SourceReference(
        document_id="synthetic-part-4-source",
        standard="SYNTHETIC-PART-4",
        edition="1",
        clause="synthetic",
        table="synthetic-hf-data",
        row="synthetic row",
        column="synthetic column",
        note="Visibly synthetic fixture only; contains no IEC numeric values.",
    )

    def table(
        table_id: str,
        row_id: str,
        row_unit: str,
        rows: tuple[str, ...],
        unit: str,
        values: tuple[str, ...],
    ) -> Table:
        return Table(
            id=table_id,
            unit=unit,
            row_axis=TableAxis(
                id=row_id,
                unit=row_unit,
                values=tuple(Decimal(value) for value in rows),
                labels=tuple(f"{row_id}-{index}" for index in range(len(rows))),
            ),
            column_axis=TableAxis(
                id=f"{table_id}_branch",
                unit="1",
                values=(Decimal(1),),
                labels=(f"{table_id}-branch",),
            ),
            cells=tuple(
                TableCell(
                    row=index,
                    column=0,
                    value=Decimal(value),
                    unit=unit,
                    source=reference.model_copy(update={"row": row, "column": "synthetic"}),
                )
                for index, (row, value) in enumerate(zip(rows, values, strict=True))
            ),
            supported_ranges=(
                SupportedRange(
                    variable=row_id,
                    minimum=Decimal(rows[0]),
                    maximum=Decimal(rows[-1]),
                    unit=row_unit,
                    source=reference,
                ),
            ),
            interpolation="linear" if len(rows) > 1 else "none",
            source=reference,
        )

    hf_tables = (
        table(
            "synthetic-hf-clearance-stress",
            "periodic_peak_v",
            "V",
            ("100", "600"),
            "mm",
            ("1", "6"),
        ),
        table(
            "synthetic-hf-frequency-factor",
            "frequency_hz",
            "Hz",
            ("30000", "100000"),
            "1",
            ("1", "2"),
        ),
        table(
            "synthetic-hf-creepage-stress",
            "periodic_peak_v",
            "V",
            ("100", "600"),
            "mm",
            ("0.5", "3"),
        ),
        table(
            "synthetic-hf-critical-frequency-scale",
            "synthetic_constant",
            "1",
            ("1",),
            "Hz",
            ("10000",),
        ),
        table(
            "synthetic-hf-iteration-tolerance",
            "synthetic_constant",
            "1",
            ("1",),
            "mm",
            ("0.2",),
        ),
        table(
            "synthetic-hf-iteration-limit",
            "synthetic_constant",
            "1",
            ("1",),
            "iterations",
            ("10",),
        ),
        table(
            "synthetic-altitude-factor",
            "altitude_m",
            "m",
            ("2000", "4000", "6000"),
            "1",
            ("1", "1.2", "1.5"),
        ),
    )

    def parameter_set(*parameters: tuple[str, str]) -> tuple[ParameterSet, ...]:
        return (
            ParameterSet(
                id="synthetic-default",
                parameters=tuple(Parameter(name=name, unit=unit) for name, unit in parameters),
                source=reference,
            ),
        )

    hf_distance = Multiply(
        operands=(
            LinearInterpolate(
                table_id="synthetic-hf-clearance-stress",
                x=Variable(name="periodic_peak_v"),
            ),
            LinearInterpolate(
                table_id="synthetic-hf-frequency-factor",
                x=Variable(name="frequency_hz"),
            ),
        )
    )
    direct = Formula(
        id="synthetic-hf-inhomogeneous-clearance",
        expression=hf_distance,
        unit="mm",
        parameter_sets=parameter_set(
            ("periodic_peak_v", "V"),
            ("frequency_hz", "Hz"),
        ),
        latex="d_{hf,synthetic}=g(U_p)h(f)",
        applicability="Synthetic direct inhomogeneous Part 4 route.",
        source=reference,
    )
    homogeneous = Formula(
        id="synthetic-hf-homogeneous-clearance",
        expression=Select(
            condition=Compare(
                comparison="gt",
                left=Variable(name="frequency_hz"),
                right=Variable(name="critical_frequency_hz"),
            ),
            if_true=Divide(
                numerator=Add(
                    operands=(
                        Variable(name="clearance_mm"),
                        hf_distance,
                    )
                ),
                denominator=Literal(value=Decimal(2)),
            ),
            if_false=hf_distance,
        ),
        unit="mm",
        parameter_sets=parameter_set(
            ("periodic_peak_v", "V"),
            ("frequency_hz", "Hz"),
            ("critical_frequency_hz", "Hz"),
            ("clearance_mm", "mm"),
        ),
        latex="d_{n+1,synthetic}=q(d_n,U_p,f,f_c)",
        applicability="Synthetic bounded homogeneous Part 4 route.",
        source=reference,
    )
    critical_frequency = Formula(
        id="synthetic-hf-critical-frequency",
        expression=Multiply(
            operands=(
                Lookup(
                    table_id="synthetic-hf-critical-frequency-scale",
                    row=Literal(value=Decimal(1)),
                    column=Literal(value=Decimal(1)),
                ),
                Divide(
                    numerator=Variable(name="radius_mm"),
                    denominator=Variable(name="clearance_mm"),
                ),
            )
        ),
        unit="Hz",
        parameter_sets=parameter_set(
            ("radius_mm", "mm"),
            ("clearance_mm", "mm"),
        ),
        latex="f_{c,synthetic}=k r/d",
        source=reference,
    )
    radius_criterion = Formula(
        id="synthetic-hf-radius-criterion",
        expression=Compare(
            comparison="ge",
            left=Divide(
                numerator=Variable(name="radius_mm"),
                denominator=Variable(name="clearance_mm"),
            ),
            right=Literal(value=Decimal("0.5")),
        ),
        unit="bool",
        parameter_sets=parameter_set(
            ("radius_mm", "mm"),
            ("clearance_mm", "mm"),
        ),
        latex="r/d\\geq k_{synthetic}",
        source=reference,
    )
    functional_applicability = Formula(
        id="synthetic-hf-functional-applicability",
        expression=Compare(
            comparison="eq",
            left=Literal(value=Decimal(1)),
            right=Literal(value=Decimal(1)),
        ),
        unit="bool",
        latex="a_{functional,synthetic}=1",
        source=reference,
    )
    tolerance = Formula(
        id="synthetic-hf-tolerance",
        expression=Lookup(
            table_id="synthetic-hf-iteration-tolerance",
            row=Literal(value=Decimal(1)),
            column=Literal(value=Decimal(1)),
        ),
        unit="mm",
        source=reference,
    )
    iteration_limit = Formula(
        id="synthetic-hf-iteration-limit",
        expression=Lookup(
            table_id="synthetic-hf-iteration-limit",
            row=Literal(value=Decimal(1)),
            column=Literal(value=Decimal(1)),
        ),
        unit="iterations",
        source=reference,
    )
    altitude = Formula(
        id="synthetic-altitude-correction",
        expression=LinearInterpolate(
            table_id="synthetic-altitude-factor",
            x=Variable(name="altitude_m"),
        ),
        unit="1",
        parameter_sets=parameter_set(("altitude_m", "m")),
        supported_ranges=(
            SupportedRange(
                variable="altitude_m",
                minimum=Decimal(2000),
                maximum=Decimal(6000),
                unit="m",
                source=reference,
            ),
        ),
        latex="k_{alt,synthetic}=k(h)",
        source=reference,
    )
    hf_creepage = Formula(
        id="synthetic-hf-creepage",
        expression=Multiply(
            operands=(
                LinearInterpolate(
                    table_id="synthetic-hf-creepage-stress",
                    x=Variable(name="periodic_peak_v"),
                ),
                LinearInterpolate(
                    table_id="synthetic-hf-frequency-factor",
                    x=Variable(name="frequency_hz"),
                ),
            )
        ),
        unit="mm",
        parameter_sets=parameter_set(
            ("periodic_peak_v", "V"),
            ("frequency_hz", "Hz"),
        ),
        latex="l_{hf,synthetic}=p(U_p)h(f)",
        source=reference,
    )

    mapping_specs: list[tuple[str, str, str]] = [
        (
            "functional_hf_applicability",
            ("iec60664-4:functional_applicability:stress=periodic_peak_v:frequency=frequency_hz"),
            functional_applicability.id,
        ),
        (
            "hf_iteration_tolerance",
            "iec60664-4:field_iteration:tolerance",
            tolerance.id,
        ),
        (
            "hf_iteration_limit",
            "iec60664-4:field_iteration:max_iterations",
            iteration_limit.id,
        ),
        (
            "altitude_correction",
            "iec60664-1:altitude_correction:base=2000m",
            altitude.id,
        ),
    ]
    for field in ("homogeneous", "approximately_homogeneous"):
        mapping_specs.extend(
            (
                (
                    f"hf_critical_frequency_{field}",
                    f"iec60664-4:critical_frequency:field={field}",
                    critical_frequency.id,
                ),
                (
                    f"hf_radius_criterion_{field}",
                    f"iec60664-4:radius_criterion:field={field}",
                    radius_criterion.id,
                ),
            )
        )
    for kind in ("functional", "basic", "reinforced"):
        # Pollution degree 1 routes cover the inner-layer recalculation.
        for pollution in (2, 1):
            suffix = "" if pollution == 2 else f"_pd{pollution}"
            for field in (
                "inhomogeneous",
                "homogeneous",
                "approximately_homogeneous",
            ):
                target = direct.id if field == "inhomogeneous" else homogeneous.id
                mapping_specs.append(
                    (
                        f"{kind}_hf_clearance_{field}{suffix}",
                        (
                            f"iec60664-4:clearance:{kind}:stress=periodic_peak_v:"
                            f"frequency=frequency_hz:field={field}:pollution={pollution}"
                        ),
                        target,
                    )
                )
            mapping_specs.append(
                (
                    f"{kind}_hf_creepage{suffix}",
                    (
                        f"iec60664-4:creepage:{kind}:stress=periodic_peak_v:"
                        f"frequency=frequency_hz:construction=other:"
                        f"pollution={pollution}:material=I"
                    ),
                    hf_creepage.id,
                )
            )
            part1_clause = "5.2.4" if kind == "functional" else "5.2.5"
            for field in ("homogeneous", "approximately_homogeneous"):
                for treatment in ("impulse", "periodic"):
                    target = next(
                        mapping.target_rule_id
                        for mapping in base.mappings
                        if mapping.source_rule_id
                        == (
                            f"iec60664-1:{part1_clause}:{kind}_clearance:"
                            f"candidate={treatment}:field=inhomogeneous:pollution={pollution}"
                        )
                    )
                    mapping_specs.append(
                        (
                            f"{kind}_part1_{treatment}_{field}{suffix}",
                            (
                                f"iec60664-1:{part1_clause}:{kind}_clearance:"
                                f"candidate={treatment}:field={field}:pollution={pollution}"
                            ),
                            target,
                        )
                    )

    return base.model_copy(
        update={
            "manifest": base.manifest.model_copy(
                update={
                    "source_documents": (
                        *base.manifest.source_documents,
                        SourceDocument(
                            id="synthetic-part-4-source",
                            standard="SYNTHETIC-PART-4",
                            edition="1",
                            sha256="c" * 64,
                        ),
                    )
                }
            ),
            "tables": (*base.tables, *hf_tables),
            "formulas": (
                *base.formulas,
                direct,
                homogeneous,
                critical_frequency,
                radius_criterion,
                functional_applicability,
                tolerance,
                iteration_limit,
                altitude,
                hf_creepage,
            ),
            "mappings": (
                *base.mappings,
                *(
                    CompatibilityMapping(
                        id=mapping_id,
                        source_rule_id=source_rule_id,
                        target_rule_id=target_rule_id,
                        approved=True,
                        source=reference,
                    )
                    for mapping_id, source_rule_id, target_rule_id in mapping_specs
                ),
            ),
        }
    )


def synthetic_dvc_rule_package(*, edition: str = EDITION) -> RulePackage:
    """A DVC-only package in the semantic shape the real Table 2/3 projection produces.

    Shape only. The reviewed selectors a real package carries are licensed content and are
    not reproduced here: this fixture invents its own smaller axes out of the public
    selector vocabulary, so it exercises the adapter's contract without stating the
    source's own reading of any row or column. Four Table 2 columns and two Table 3
    columns, chosen to cover every route the adapter can take, and every numeric cell is
    an invented placeholder.

    Two things the adapter has to handle are built in deliberately. ``dvc_c`` is split by
    environment while ``dvc_as`` and ``dvc_b`` are not, so both entries of
    ``READ_ENVIRONMENTS`` are exercised and the wet reading carries different numbers from
    the dry one. And the protection matrix is not exhaustive, so almost every combination
    of its declared vocabularies answers ``no_match``.

    ``edition`` lets a test build a package that carries the right semantic IDs but the
    wrong source edition, to exercise the "wrong-edition package is refused" path without
    needing a second, differently-shaped fixture.
    """
    reference = SourceReference(
        document_id="synthetic-dvc-source",
        standard=STANDARD,
        edition=edition,
        clause="synthetic-clause",
        table="synthetic-table-2",
        row="synthetic row",
        column="synthetic column",
        note="Synthetic fixture only; contains no IEC numeric values.",
    )

    def cell_source(row: str, column: str) -> SourceReference:
        return reference.model_copy(update={"row": row, "column": column})

    # (designation, environment) - the fixture's own invented row axis.
    dvc_as_row = ("dvc_as", "not_applicable")
    dvc_b_row = ("dvc_b", "not_applicable")
    dvc_c_dry_row = ("dvc_c", "dry")
    dvc_c_wet_row = ("dvc_c", "wet_and_saltwater_wet")
    table_2_rows = (dvc_as_row, dvc_b_row, dvc_c_dry_row, dvc_c_wet_row)

    # (quantity, basis, operating_context) - the fixture's own invented column axis.
    rms_column = ("working_voltage", "ac_rms", "normal")
    mean_column = ("working_voltage", "dc_mean", "normal")
    impulse_column = ("impulse_withstand", "ac_peak_or_dc", "normal")
    fault_column = ("fault_voltage", "not_applicable", "single_fault_or_abnormal")
    table_2_columns = (rms_column, mean_column, impulse_column, fault_column)

    def categorical(name: str, values: Iterable[str]) -> DecisionInput:
        return DecisionInput(
            name=name, kind="categorical", allowed_values=tuple(sorted(set(values)))
        )

    table_2_inputs = (
        categorical("dvc", (row[0] for row in table_2_rows)),
        categorical("environment", (row[1] for row in table_2_rows)),
        categorical("quantity", (column[0] for column in table_2_columns)),
        categorical("basis", (column[1] for column in table_2_columns)),
        categorical("operating_context", (column[2] for column in table_2_columns)),
        DecisionInput(name="unit", kind="categorical", allowed_values=("V",)),
    )

    def matchers(row: tuple[str, str], column: tuple[str, str, str]) -> tuple[Matcher, ...]:
        return (
            Matcher(input="dvc", op="equals", values=(row[0],)),
            Matcher(input="environment", op="equals", values=(row[1],)),
            Matcher(input="quantity", op="equals", values=(column[0],)),
            Matcher(input="basis", op="equals", values=(column[1],)),
            Matcher(input="operating_context", op="equals", values=(column[2],)),
            Matcher(input="unit", op="equals", values=("V",)),
        )

    def cell_of(row: tuple[str, ...], column: tuple[str, ...]) -> SourceReference:
        return cell_source("/".join(row), "/".join(column))

    numeric_cells = (
        (dvc_as_row, rms_column, Decimal(11)),
        (dvc_as_row, mean_column, Decimal(22)),
        (dvc_as_row, impulse_column, Decimal(33)),
        (dvc_b_row, rms_column, Decimal(55)),
        (dvc_b_row, mean_column, Decimal(66)),
        # DVC C is split by environment here, and only the dry reading may ever be shown.
        (dvc_c_dry_row, rms_column, Decimal(88)),
        (dvc_c_wet_row, rms_column, Decimal(99)),
        (dvc_c_wet_row, mean_column, Decimal(100)),
    )
    voltage_limits = DecisionRule(
        id=ids.DVC_VOLTAGE_LIMITS,
        inputs=table_2_inputs,
        outputs=(DecisionOutput(name="voltage_limit", kind="numeric", unit="V"),),
        rows=tuple(
            DecisionRow(
                matchers=matchers(row, column),
                values=(DecisionValue(name="voltage_limit", numeric=value, unit="V"),),
                source=cell_of(row, column),
            )
            for row, column, value in numeric_cells
        ),
        exhaustive=False,
        source=reference,
    )

    fault_time_cells = ((dvc_as_row, fault_column), (dvc_b_row, fault_column))
    fault_time_reference = DecisionRule(
        id=f"{ids.DVC_VOLTAGE_LIMITS}.fault_time_reference",
        inputs=table_2_inputs,
        outputs=(DecisionOutput(name="fault_time_voltage", kind="reference"),),
        rows=tuple(
            DecisionRow(
                matchers=matchers(row, column),
                values=(
                    DecisionValue(name="fault_time_voltage", reference=ids.DVC_FAULT_TIME_VOLTAGE),
                ),
                source=cell_of(row, column),
            )
            for row, column in fault_time_cells
        ),
        exhaustive=False,
        source=reference,
    )

    impulse_cells = ((dvc_b_row, impulse_column),)
    impulse_reference = DecisionRule(
        id=f"{ids.DVC_VOLTAGE_LIMITS}.impulse_reference",
        inputs=table_2_inputs,
        outputs=(
            DecisionOutput(name="ac_reference", kind="reference"),
            DecisionOutput(name="dc_reference", kind="reference"),
        ),
        rows=tuple(
            DecisionRow(
                matchers=matchers(row, column),
                values=(
                    DecisionValue(
                        name="ac_reference",
                        reference=f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.ac",
                    ),
                    DecisionValue(
                        name="dc_reference",
                        reference=f"{ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC}.dc",
                    ),
                ),
                source=cell_of(row, column),
            )
            for row, column in impulse_cells
        ),
        exhaustive=False,
        source=reference,
    )

    not_applicable_cells = ((dvc_c_dry_row, fault_column),)
    not_applicable = DecisionRule(
        id=f"{ids.DVC_VOLTAGE_LIMITS}.not_applicable",
        inputs=table_2_inputs,
        outputs=(DecisionOutput(name="applicable", kind="boolean"),),
        rows=tuple(
            DecisionRow(
                matchers=matchers(row, column),
                values=(DecisionValue(name="applicable", boolean=False),),
                source=cell_of(row, column),
            )
            for row, column in not_applicable_cells
        ),
        exhaustive=False,
        source=reference,
    )

    # (target, pe_relationship, access_context, person_scope, adjacent_dvc) - again the
    # fixture's own invented column axis, not the source's reviewed one.
    accessible_target = (
        "accessible_part",
        "connected_to_pe",
        "general_access",
        "ordinary_or_skilled",
        "not_applicable",
    )
    adjacent_target = (
        "adjacent_circuit",
        "not_applicable",
        "not_applicable",
        "not_applicable",
        "dvc_b",
    )
    protection_targets = (accessible_target, adjacent_target)
    protection_inputs = (
        categorical("dvc", ("dvc_as", "dvc_b", "dvc_c")),
        *(
            categorical(name, (target[index] for target in protection_targets))
            for index, name in enumerate(PROTECTION_TARGET_DIMENSIONS)
        ),
    )
    protection_cells = {
        ("dvc_as", accessible_target): "none",
        ("dvc_as", adjacent_target): "none",
        ("dvc_b", accessible_target): "basic_protection",
        ("dvc_b", adjacent_target): "none",
        ("dvc_c", accessible_target): "enhanced_protection",
        ("dvc_c", adjacent_target): "basic_protection",
    }
    protection_matrix = DecisionRule(
        id=ids.DVC_PROTECTION_MATRIX,
        inputs=protection_inputs,
        outputs=(
            DecisionOutput(
                name="protection_requirement",
                kind="categorical",
                allowed_values=("none", "basic_protection", "enhanced_protection"),
            ),
        ),
        rows=tuple(
            DecisionRow(
                matchers=(
                    Matcher(input="dvc", op="equals", values=(designation,)),
                    *(
                        Matcher(input=name, op="equals", values=(target[index],))
                        for index, name in enumerate(PROTECTION_TARGET_DIMENSIONS)
                    ),
                ),
                values=(DecisionValue(name="protection_requirement", categorical=requirement),),
                source=cell_of((designation,), target),
            )
            for (designation, target), requirement in protection_cells.items()
        ),
        # Not exhaustive, exactly as the real projection now is: five structured target
        # dimensions multiply out far past the combinations any reviewed column carries.
        exhaustive=False,
        source=reference,
    )

    return RulePackage(
        manifest=Manifest(
            schema_version=RULE_SCHEMA_VERSION,
            package_id="00000000-0000-0000-0000-00000000000a",
            version="dvc-synthetic-1",
            importer_version="test-1",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            source_documents=(
                SourceDocument(
                    id="synthetic-dvc-source",
                    standard=STANDARD,
                    edition=edition,
                    sha256="d" * 64,
                ),
            ),
            approved=True,
            compatible=True,
            approval_records=(
                ApprovalRecord(
                    action="approval",
                    actor="Synthetic Reviewer",
                    recorded_at=datetime(2026, 1, 2, tzinfo=UTC),
                    notes="Synthetic DVC data reviewed.",
                ),
            ),
        ),
        tables=(),
        formulas=(),
        mappings=(),
        decisions=(
            voltage_limits,
            fault_time_reference,
            impulse_reference,
            not_applicable,
            protection_matrix,
        ),
    )


#: The data columns of the two synthetic Table 7 lookups, named the way the importer recipe
#: names the real ones. The identifiers are the contract a consumer selects a column by; the
#: cells behind them are this fixture's invention.
SYNTHETIC_IMPULSE_COLUMNS = (
    "impulse_ovc_1_v",
    "impulse_ovc_2_v",
    "impulse_ovc_3_v",
    "impulse_ovc_4_v",
)
SYNTHETIC_TOV_COLUMNS = ("temporary_overvoltage_rms_v", "temporary_overvoltage_peak_v")

#: The band edges of the two parallel system-voltage axes. The DC axis reaches past everything
#: the AC axis carries, because the source's own highest band is DC-only, and a consumer that
#: never leaves the shared bands would never show that it looks a DC supply up on the DC axis
#: at all. Every edge here is invented. The DC-only edge is placed so that the band's midpoint
#: is a round voltage: the temporary-overvoltage lookup interpolates, and a midpoint lookup is
#: the one a test can assert an exact figure for without repeating the interpolation itself.
SYNTHETIC_SHARED_SYSTEM_VOLTAGE_BANDS = (Decimal(11), Decimal(22), Decimal(33))
SYNTHETIC_DC_ONLY_SYSTEM_VOLTAGE_BAND = Decimal(2967)
SYNTHETIC_SYSTEM_VOLTAGE_BANDS: dict[str, tuple[Decimal, ...]] = {
    "ac": SYNTHETIC_SHARED_SYSTEM_VOLTAGE_BANDS,
    "dc": (*SYNTHETIC_SHARED_SYSTEM_VOLTAGE_BANDS, SYNTHETIC_DC_ONLY_SYSTEM_VOLTAGE_BAND),
}

#: The measure vocabulary the real resolution rule answers with. Reproduced because a
#: consumer's behaviour depends on the token, not on the reading behind it.
SYNTHETIC_SYSTEM_VOLTAGE_MEASURES = (
    "phase_to_earth_rms",
    "phase_to_artificial_neutral_rms",
    "phase_to_phase_rms",
    "between_supply_conductors_rms",
    "pre_rectifier_ac_rms",
    "highest_pre_rectifier_ac_rms_at_bridge",
)


def _measure(name: str) -> DecisionValue:
    return DecisionValue(name="system_voltage_measure", categorical=name)


def _is(name: str, *values: str) -> Matcher:
    return Matcher(input=name, op="equals" if len(values) == 1 else "in", values=values)


#: Which arrangement selects which measure. **Invented**, and deliberately not the source's own
#: reading: what these rows exist to exercise is that a consumer asks the rule instead of
#: deciding for itself, that one arrangement can answer the impulse and temporary-overvoltage
#: questions differently, and that an arrangement no row covers blocks. Reading any normative
#: meaning off this table would be reading the fixture's invention.
_SYNTHETIC_SYSTEM_VOLTAGE_ROWS: tuple[tuple[tuple[Matcher, ...], DecisionValue], ...] = (
    (
        (_is("supply_kind", "mains"), _is("input_topology", "series_rectifier_bridges")),
        _measure("highest_pre_rectifier_ac_rms_at_bridge"),
    ),
    (
        (_is("supply_kind", "mains"), _is("input_topology", "rectified_dc")),
        _measure("pre_rectifier_ac_rms"),
    ),
    (
        (
            _is("supply_kind", "mains"),
            _is("phase_system", "three_phase_it"),
            _is("calculation_purpose", "impulse"),
        ),
        _measure("phase_to_artificial_neutral_rms"),
    ),
    (
        (
            _is("supply_kind", "mains"),
            _is("phase_system", "three_phase_it"),
            _is("calculation_purpose", "temporary_overvoltage"),
        ),
        _measure("phase_to_phase_rms"),
    ),
    (
        (_is("supply_kind", "mains"), _is("phase_system", "three_phase_delta")),
        _measure("phase_to_phase_rms"),
    ),
    (
        (_is("supply_kind", "mains"), _is("phase_system", "single_phase_it")),
        _measure("between_supply_conductors_rms"),
    ),
    (
        (_is("supply_kind", "mains"), _is("phase_system", "three_phase_star", "single_phase")),
        _measure("phase_to_earth_rms"),
    ),
    ((_is("supply_kind", "non_mains"),), _measure("between_supply_conductors_rms")),
)


def synthetic_supply_rule_package(*, edition: str = EDITION) -> RulePackage:
    """A supply-only package in the semantic shape the real supply projections produce.

    Shape only. Every number here is invented: the band boundaries, the cell values and the
    frequency are this fixture's own, and no reviewed reading of any clause is reproduced. What
    is faithful is the structure the adapter resolves against - the AC and DC lookup pair per
    quantity, the DC axis reaching past the AC one, the routes beneath the reduction
    identifier, and each decision's declared input and output names.

    The two lookups differ exactly as the source's own treatment of them does: the impulse pair
    selects a band and declares no interpolation, the temporary-overvoltage pair interpolates.
    That is what lets a test prove the adapter refuses an impulse lookup that interpolates.

    The measure each arrangement resolves to is invented as well - see
    :data:`_SYNTHETIC_SYSTEM_VOLTAGE_ROWS`. What is faithful there is only that the rule answers
    with a measure name, that one arrangement may answer the two purposes differently, and that
    an arrangement nothing covers gets no answer.

    ``edition`` builds a package carrying the right identifiers under the wrong source edition,
    so the refusal of a wrong-edition package needs no second fixture.
    """
    reference = SourceReference(
        document_id="synthetic-supply-source",
        standard=STANDARD,
        edition=edition,
        clause="synthetic-clause",
        table="synthetic-supply-table",
        row="synthetic row",
        column="synthetic column",
        note="Synthetic fixture only; contains no IEC numeric values.",
    )

    def categorical(name: str, values: Iterable[str]) -> DecisionInput:
        return DecisionInput(name=name, kind="categorical", allowed_values=tuple(values))

    def lookup_pair(
        base_id: str,
        column_axis_id: str,
        column_labels: tuple[str, ...],
        *,
        interpolation: str,
        row_mode: str,
    ) -> tuple[tuple[Table, ...], tuple[Formula, ...]]:
        tables: list[Table] = []
        formulas: list[Formula] = []
        for form in ("ac", "dc"):
            row_axis_id = f"system_voltage_{form}_v"
            row_values = SYNTHETIC_SYSTEM_VOLTAGE_BANDS[form]
            column_values = tuple(Decimal(index + 1) for index in range(len(column_labels)))
            table = Table(
                id=f"{base_id}.{form}",
                unit="V",
                row_axis=TableAxis(
                    id=row_axis_id,
                    unit="V",
                    values=row_values,
                    labels=tuple(f"{row_axis_id}-{value}" for value in row_values),
                ),
                column_axis=TableAxis(
                    id=column_axis_id,
                    unit="1",
                    values=column_values,
                    labels=column_labels,
                ),
                cells=tuple(
                    TableCell(
                        row=row,
                        column=column,
                        value=Decimal((row + 1) * 100 + (column + 1) * 7),
                        unit="V",
                        source=reference,
                    )
                    for row in range(len(row_values))
                    for column in range(len(column_values))
                ),
                interpolation=interpolation,  # type: ignore[arg-type]
                source=reference,
            )
            tables.append(table)
            formulas.append(
                Formula(
                    id=f"{base_id}.{form}.lookup",
                    expression=TableSelect(
                        table_id=table.id,
                        row=Variable(name=row_axis_id),
                        column=Variable(name=column_axis_id),
                        row_mode=row_mode,  # type: ignore[arg-type]
                        column_mode="exact",
                    ),
                    unit="V",
                    # Declared because a formula naming variables and no parameter set fails
                    # the whole-package validation gate the clearance engine runs, and a real
                    # installation carries the supply rules and the clearance rules together.
                    parameter_sets=(
                        ParameterSet(
                            id=f"{base_id}.{form}.parameters",
                            parameters=(
                                Parameter(name=row_axis_id, unit="V"),
                                Parameter(name=column_axis_id, unit="1"),
                            ),
                            source=reference,
                        ),
                    ),
                    latex="U_{synthetic} = f(U_{sys}, k)",
                    applicability="Synthetic fixture only.",
                    source=reference,
                )
            )
        return tuple(tables), tuple(formulas)

    impulse_tables, impulse_formulas = lookup_pair(
        ids.SUPPLY_IMPULSE_BY_SYSTEM_VOLTAGE_OVC,
        "overvoltage_category",
        SYNTHETIC_IMPULSE_COLUMNS,
        interpolation="none",
        row_mode="ceiling",
    )
    tov_tables, tov_formulas = lookup_pair(
        ids.SUPPLY_TOV_BY_SYSTEM_VOLTAGE,
        "tov_basis",
        SYNTHETIC_TOV_COLUMNS,
        interpolation="linear",
        row_mode="linear",
    )

    overvoltage_categories = ("ovc_i", "ovc_ii", "ovc_iii", "ovc_iv")
    insulation_classes = ("functional", "basic", "supplementary", "double", "reinforced")

    system_voltage = DecisionRule(
        id=ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
        inputs=(
            categorical("supply_kind", ("mains", "non_mains")),
            categorical(
                "phase_system",
                (
                    "three_phase_star",
                    "three_phase_delta",
                    "three_phase_it",
                    "single_phase_it",
                    "single_phase",
                    "unspecified",
                ),
            ),
            categorical("earthing_arrangement", ("tn", "tt", "it", "unspecified")),
            categorical(
                "input_topology",
                ("direct", "rectified_dc", "series_rectifier_bridges", "isolated_secondary"),
            ),
            categorical("calculation_purpose", ("impulse", "temporary_overvoltage")),
        ),
        outputs=(
            DecisionOutput(
                name="system_voltage_measure",
                kind="categorical",
                allowed_values=SYNTHETIC_SYSTEM_VOLTAGE_MEASURES,
            ),
        ),
        rows=tuple(
            DecisionRow(matchers=matchers, values=(value,), source=reference)
            for matchers, value in _SYNTHETIC_SYSTEM_VOLTAGE_ROWS
        ),
        exhaustive=False,
        source=reference,
    )

    propagation = DecisionRule(
        id=ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION,
        inputs=(
            categorical("evaluated_side", ("mains", "non_mains")),
            categorical("mains_overvoltage_category", overvoltage_categories),
            categorical("non_mains_overvoltage_category", overvoltage_categories),
            DecisionInput(name="galvanic_isolation_present", kind="boolean"),
        ),
        outputs=tuple(
            DecisionOutput(name=name, kind="categorical", allowed_values=overvoltage_categories)
            for name in ("source_requirement", "transferred_requirement", "governing_requirement")
        ),
        rows=(
            DecisionRow(
                matchers=(Matcher(input="galvanic_isolation_present", op="equals", boolean=True),),
                values=tuple(
                    DecisionValue(name=name, categorical="ovc_ii")
                    for name in (
                        "source_requirement",
                        "transferred_requirement",
                        "governing_requirement",
                    )
                ),
                source=reference,
            ),
        ),
        exhaustive=False,
        source=reference,
    )

    barrier = DecisionRule(
        id=ids.SUPPLY_VERIFIED_BARRIER_TRANSFER,
        inputs=(
            DecisionInput(name="galvanic_isolation_verified", kind="boolean"),
            categorical("isolation_evidence_kind", ("none", "test", "calculation")),
            categorical("downstream_connection_kind", ("no_isolation", "verified_isolation")),
        ),
        outputs=(
            DecisionOutput(name="transfer_permitted", kind="boolean"),
            DecisionOutput(
                name="combined_circuit_requirement",
                kind="categorical",
                allowed_values=("synthetic_requirement",),
            ),
            DecisionOutput(name="propagates_to_connected_circuits", kind="boolean"),
        ),
        rows=(
            DecisionRow(
                matchers=(
                    Matcher(input="galvanic_isolation_verified", op="equals", boolean=False),
                ),
                values=(
                    DecisionValue(name="transfer_permitted", boolean=False),
                    DecisionValue(
                        name="combined_circuit_requirement",
                        categorical="synthetic_requirement",
                    ),
                    DecisionValue(name="propagates_to_connected_circuits", boolean=True),
                ),
                source=reference,
            ),
        ),
        exhaustive=False,
        source=reference,
    )

    def spd_reduction(route: str) -> DecisionRule:
        return DecisionRule(
            id=route,
            inputs=(
                categorical("source_overvoltage_category", overvoltage_categories),
                categorical("insulation_class", insulation_classes),
                DecisionInput(name="part_of_category_reduction", kind="boolean"),
            ),
            outputs=(
                DecisionOutput(name="reduction_permitted", kind="boolean"),
                DecisionOutput(
                    name="reduced_category", kind="categorical", allowed_values=("ovc_ii",)
                ),
            ),
            rows=(
                DecisionRow(
                    matchers=(
                        Matcher(input="part_of_category_reduction", op="equals", boolean=True),
                    ),
                    values=(
                        DecisionValue(name="reduction_permitted", boolean=True),
                        DecisionValue(name="reduced_category", categorical="ovc_ii"),
                    ),
                    source=reference,
                ),
            ),
            exhaustive=False,
            source=reference,
        )

    def spd_device_monitoring(route: str) -> DecisionRule:
        return DecisionRule(
            id=f"{route}.device_monitoring",
            inputs=(DecisionInput(name="device_degradable", kind="boolean"),),
            outputs=(
                DecisionOutput(name="monitoring_required", kind="boolean"),
                DecisionOutput(name="status_indication_required", kind="boolean"),
                DecisionOutput(name="monitoring_reference", kind="reference"),
            ),
            rows=(
                DecisionRow(
                    matchers=(Matcher(input="device_degradable", op="equals", boolean=True),),
                    values=(
                        DecisionValue(name="monitoring_required", boolean=True),
                        DecisionValue(name="status_indication_required", boolean=True),
                        DecisionValue(
                            name="monitoring_reference",
                            reference=f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring",
                        ),
                    ),
                    source=reference,
                ),
            ),
            exhaustive=False,
            source=reference,
        )

    spd_monitoring = DecisionRule(
        id=f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring",
        inputs=(
            categorical("device_placement", ("internal_to_pecs", "external_to_pecs")),
            categorical("insulation_class", insulation_classes),
            DecisionInput(name="device_degradable", kind="boolean"),
            DecisionInput(name="part_of_category_reduction", kind="boolean"),
        ),
        outputs=(
            DecisionOutput(name="reduction_permitted", kind="boolean"),
            DecisionOutput(
                name="reduced_category", kind="categorical", allowed_values=("not_reduced",)
            ),
            DecisionOutput(name="monitoring_required", kind="boolean"),
            DecisionOutput(name="status_indication_required", kind="boolean"),
            DecisionOutput(
                name="verification_reference",
                kind="categorical",
                allowed_values=("synthetic_verification", "not_required"),
            ),
            DecisionOutput(name="reinforced_floor_applies", kind="boolean"),
        ),
        rows=(
            DecisionRow(
                matchers=(
                    Matcher(input="device_placement", op="equals", values=("internal_to_pecs",)),
                ),
                values=(
                    DecisionValue(name="reduction_permitted", boolean=False),
                    DecisionValue(name="reduced_category", categorical="not_reduced"),
                    DecisionValue(name="monitoring_required", boolean=True),
                    DecisionValue(name="status_indication_required", boolean=True),
                    DecisionValue(
                        name="verification_reference", categorical="synthetic_verification"
                    ),
                    DecisionValue(name="reinforced_floor_applies", boolean=False),
                ),
                source=reference,
            ),
        ),
        exhaustive=False,
        source=reference,
    )

    transformer = DecisionRule(
        id=ids.SUPPLY_HF_TRANSFORMER_ATTENUATION,
        inputs=(
            categorical("circuit_dvc", ("dvc_as", "dvc_b", "dvc_c")),
            DecisionInput(name="transformer_frequency_hz", kind="numeric", unit="Hz"),
            DecisionInput(name="isolation_provided", kind="boolean"),
            categorical("attenuation_evidence_kind", ("none", "test", "simulation")),
        ),
        outputs=(
            DecisionOutput(name="working_voltage_basis_permitted", kind="boolean"),
            DecisionOutput(
                name="required_evidence_kinds",
                kind="categorical",
                allowed_values=("synthetic_showing", "already_provided"),
            ),
        ),
        rows=(
            DecisionRow(
                matchers=(
                    Matcher(input="transformer_frequency_hz", op="range", minimum=Decimal(4321)),
                    Matcher(input="isolation_provided", op="equals", boolean=True),
                ),
                values=(
                    DecisionValue(name="working_voltage_basis_permitted", boolean=True),
                    DecisionValue(name="required_evidence_kinds", categorical="already_provided"),
                ),
                source=reference,
            ),
        ),
        exhaustive=False,
        source=reference,
    )

    return RulePackage(
        manifest=Manifest(
            schema_version=RULE_SCHEMA_VERSION,
            package_id="00000000-0000-0000-0000-00000000000b",
            version="supply-synthetic-1",
            importer_version="test-1",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            source_documents=(
                SourceDocument(
                    id="synthetic-supply-source",
                    standard=STANDARD,
                    edition=edition,
                    sha256="e" * 64,
                ),
            ),
            approved=True,
            compatible=True,
            approval_records=(
                ApprovalRecord(
                    action="approval",
                    actor="Synthetic Reviewer",
                    recorded_at=datetime(2026, 1, 2, tzinfo=UTC),
                    notes="Synthetic supply data reviewed.",
                ),
            ),
        ),
        tables=(*impulse_tables, *tov_tables),
        formulas=(*impulse_formulas, *tov_formulas),
        mappings=(),
        decisions=(
            system_voltage,
            propagation,
            barrier,
            spd_reduction(f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains"),
            spd_reduction(f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains"),
            spd_monitoring,
            spd_device_monitoring(f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains"),
            spd_device_monitoring(f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains"),
            transformer,
        ),
    )


def merged_rule_package(*packages: RulePackage, path: Path) -> RulePackage:
    """One package answering everything ``packages`` answer between them.

    A real installation carries the clearance rules and the supply rules together; the
    fixtures are separate only because the slices that built them were. This is a field-wise
    union - no content is added, only the one shape a whole-package validation needs. Written
    to ``path`` and reloaded so the archive recomputes the checksums the engine's gate reads.

    A rule two of the fixtures both declare is kept once, from the **first** package that
    declares it. Two fixtures naming one rule is how they overlap rather than a conflict, and
    concatenating both copies fails the unique-id gate before anything can be read; the
    earlier package wins so a caller orders the argument list by which content it wants.
    """

    first = packages[0]
    documents = {
        document.id: document
        for package in packages
        for document in package.manifest.source_documents
    }

    def _by_id(field: str) -> tuple[object, ...]:
        merged: dict[str, object] = {}
        for package in packages:
            for item in getattr(package, field):
                merged.setdefault(item.id, item)
        return tuple(merged.values())

    candidate = first.model_copy(
        update={
            "manifest": first.manifest.model_copy(
                update={"source_documents": tuple(documents.values())}
            ),
            "tables": _by_id("tables"),
            "formulas": _by_id("formulas"),
            "decisions": _by_id("decisions"),
            "curves": _by_id("curves"),
            "procedures": _by_id("procedures"),
            "guidance": _by_id("guidance"),
            "mappings": _by_id("mappings"),
            "checksums": {},
            "package_sha256": None,
        }
    )
    write_rule_package(path, candidate)
    return load_rule_package(path)


#: The two Table 26 procedure fields the fixture fills. Neutral names for what each step is
#: about; the wording behind them in a real package is licensed and is not reproduced here.
_SYNTHETIC_PROCEDURE_STEPS = ("synthetic connection step", "synthetic measurement step")


def synthetic_verification_rule_package(*, edition: str = EDITION) -> RulePackage:
    """A verification-only package in the semantic shape the real Table 26-30 and clause
    projections produce.

    Shape only. Every number, step and condition here is invented: the band boundaries, the
    cell values and the step wording are this fixture's own, and no reviewed reading of any
    clause, table row or table column is reproduced. What is faithful is the structure
    ``read_verification_rules`` resolves against - the route each identifier projects, the test
    kind each procedure declares, the classification vocabulary, the axes each selection table
    is keyed by, and each decision's declared input and output names.

    Two shapes are built in deliberately because the adapter has to handle them. The partial
    discharge and foil procedures each point at the gate projected from the same source
    statement, which is what lets a test prove that a procedure pointing somewhere else is
    refused. And the electrical preconditioning route and the foil procedure declare no
    classification at all, exactly as the real projections do where the cross-reference matrix
    has no row for the clause.

    ``edition`` builds a package carrying the right identifiers under the wrong source edition,
    so the refusal of a wrong-edition package needs no second fixture.
    """
    reference = SourceReference(
        document_id="synthetic-verification-source",
        standard=STANDARD,
        edition=edition,
        clause="synthetic-clause",
        table="synthetic-verification-table",
        note="Synthetic fixture only; contains no IEC numeric values.",
    )

    def steps() -> tuple[ProcedureStep, ...]:
        return tuple(
            ProcedureStep(order=order, text=text, source=reference)
            for order, text in enumerate(_SYNTHETIC_PROCEDURE_STEPS, start=1)
        )

    def procedure(
        rule_id: str,
        test_kind: str,
        *,
        classifications: tuple[str, ...] = (),
        applicability_rule_id: str | None = None,
    ) -> ProcedureRule:
        return ProcedureRule(
            id=rule_id,
            test_kind=test_kind,
            classifications=classifications,
            procedure_steps=steps(),
            applicability_rule_id=applicability_rule_id,
            source=reference,
        )

    def table(table_id: str, row_axis_id: str, column_axis_id: str) -> Table:
        row_values = (Decimal(13), Decimal(26), Decimal(39))
        column_values = (Decimal(1), Decimal(2))
        return Table(
            id=table_id,
            unit="V",
            row_axis=TableAxis(
                id=row_axis_id,
                unit="V",
                values=row_values,
                labels=tuple(f"{row_axis_id}-{value}" for value in row_values),
            ),
            column_axis=TableAxis(
                id=column_axis_id,
                unit="1",
                values=column_values,
                labels=tuple(f"{column_axis_id}-{value}" for value in column_values),
            ),
            cells=tuple(
                TableCell(
                    row=row,
                    column=column,
                    value=Decimal((row + 1) * 200 + (column + 1) * 3),
                    unit="V",
                    source=reference,
                )
                for row in range(len(row_values))
                for column in range(len(column_values))
            ),
            interpolation="linear",
            source=reference,
        )

    def boolean_gate(
        rule_id: str, inputs: tuple[str, ...], outputs: tuple[str, ...]
    ) -> DecisionRule:
        """A decision whose declared names are the contract, answering true to everything."""
        return DecisionRule(
            id=rule_id,
            inputs=tuple(DecisionInput(name=name, kind="boolean") for name in inputs),
            outputs=tuple(DecisionOutput(name=name, kind="boolean") for name in outputs),
            rows=(
                DecisionRow(
                    matchers=tuple(
                        Matcher(input=name, op="equals", boolean=True) for name in inputs
                    ),
                    values=tuple(DecisionValue(name=name, boolean=True) for name in outputs),
                    source=reference,
                ),
            ),
            exhaustive=False,
            source=reference,
        )

    partial_discharge_gate = DecisionRule(
        id=f"{ids.TEST_PARTIAL_DISCHARGE}.applicability",
        inputs=(DecisionInput(name="partial_discharge_test_voltage_declared", kind="boolean"),),
        outputs=(
            DecisionOutput(
                name="partial_discharge_test",
                kind="categorical",
                allowed_values=("required", "engineering_input_required"),
            ),
        ),
        rows=tuple(
            DecisionRow(
                matchers=(
                    Matcher(
                        input="partial_discharge_test_voltage_declared",
                        op="equals",
                        boolean=declared,
                    ),
                ),
                values=(DecisionValue(name="partial_discharge_test", categorical=outcome),),
                source=reference,
            )
            for declared, outcome in ((True, "required"), (False, "engineering_input_required"))
        ),
        exhaustive=False,
        source=reference,
    )
    foil_gate = DecisionRule(
        id=f"{ids.TEST_ACCESSIBLE_SURFACE_FOIL}.applicability",
        inputs=(DecisionInput(name="non_conductive_accessible_surface_present", kind="boolean"),),
        outputs=(
            DecisionOutput(name="foil_wrap_required", kind="boolean"),
            DecisionOutput(
                name="permitted_classification_substitution",
                kind="categorical",
                allowed_values=("synthetic_substitution",),
            ),
        ),
        rows=(
            DecisionRow(
                matchers=(
                    Matcher(
                        input="non_conductive_accessible_surface_present",
                        op="equals",
                        boolean=True,
                    ),
                ),
                values=(
                    DecisionValue(name="foil_wrap_required", boolean=True),
                    DecisionValue(
                        name="permitted_classification_substitution",
                        categorical="synthetic_substitution",
                    ),
                ),
                source=reference,
            ),
        ),
        exhaustive=False,
        source=reference,
    )
    preconditioning_gate = DecisionRule(
        id=f"{ids.TEST_PRECONDITIONING}.applicability",
        inputs=(
            DecisionInput(
                name="test_context",
                kind="categorical",
                allowed_values=("synthetic_electrical", "synthetic_material"),
            ),
            DecisionInput(
                name="test_purpose",
                kind="categorical",
                allowed_values=("synthetic_purpose",),
            ),
        ),
        outputs=(
            DecisionOutput(name="preconditioning_required", kind="boolean"),
            DecisionOutput(
                name="preconditioning_procedure_rule_id",
                kind="categorical",
                allowed_values=(
                    f"{ids.TEST_PRECONDITIONING}.electrical_tests",
                    f"{ids.TEST_PRECONDITIONING}.material",
                ),
            ),
        ),
        rows=tuple(
            DecisionRow(
                matchers=(Matcher(input="test_context", op="equals", values=(context,)),),
                values=(
                    DecisionValue(name="preconditioning_required", boolean=True),
                    DecisionValue(name="preconditioning_procedure_rule_id", categorical=route),
                ),
                source=reference,
            )
            for context, route in (
                ("synthetic_electrical", f"{ids.TEST_PRECONDITIONING}.electrical_tests"),
                ("synthetic_material", f"{ids.TEST_PRECONDITIONING}.material"),
            )
        ),
        exhaustive=False,
        source=reference,
    )

    curve_axis = CurveAxis(
        quantity_kind="synthetic_time",
        unit="s",
        scale="linear",
        minimum=Decimal(0),
        maximum=Decimal(10),
    )
    voltage_axis = CurveAxis(
        quantity_kind="synthetic_voltage",
        unit="V",
        scale="linear",
        minimum=Decimal(0),
        maximum=Decimal(100),
    )
    fault_time_voltage = PiecewiseCurveRule(
        id=ids.DVC_FAULT_TIME_VOLTAGE,
        variants=(
            FaultTimeVoltageVariant(
                id=f"{ids.DVC_FAULT_TIME_VOLTAGE}.synthetic-1",
                selector=FaultTimeVoltageSelector(
                    subject="accessible_circuit",
                    voltage_basis="ac_rms",
                    dvc_context=None,
                    environment_context=None,
                ),
                x_axis=curve_axis,
                y_axis=voltage_axis,
                points=(
                    CurvePoint(x=Decimal(1), y=Decimal(40)),
                    CurvePoint(x=Decimal(5), y=Decimal(20)),
                ),
                segments=(
                    CurveSegment(start=0, end=1, segment_type="continuous", interpolation="linear"),
                ),
                applicability="Synthetic fixture variant.",
                source=reference,
                reviewed_artifact_sha256="f" * 64,
            ),
        ),
        source=reference,
    )

    return RulePackage(
        manifest=Manifest(
            schema_version=RULE_SCHEMA_VERSION,
            package_id="00000000-0000-0000-0000-00000000000c",
            version="verification-synthetic-1",
            importer_version="test-1",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            source_documents=(
                SourceDocument(
                    id="synthetic-verification-source",
                    standard=STANDARD,
                    edition=edition,
                    sha256="c" * 64,
                ),
            ),
            approved=True,
            compatible=True,
            approval_records=(
                ApprovalRecord(
                    action="approval",
                    actor="Synthetic Reviewer",
                    recorded_at=datetime(2026, 1, 2, tzinfo=UTC),
                    notes="Synthetic verification data reviewed.",
                ),
            ),
        ),
        tables=(
            *(
                table(
                    f"{ids.TEST_IMPULSE_SELECTION}.{pair}.{form}",
                    f"system_voltage_{form}_v",
                    "impulse_selection_column",
                )
                for pair in ("mains_circuits", "non_mains_circuits")
                for form in ("ac", "dc")
            ),
            *(
                table(f"{base_id}.{purpose}.{form}", row_axis_id, "dielectric_test_column")
                for base_id, row_axis_id in (
                    (ids.TEST_MAINS_DIELECTRIC_VALUES, "system_voltage_v"),
                    (ids.TEST_NON_MAINS_DIELECTRIC_VALUES, "working_voltage_recurring_peak_v"),
                )
                for purpose in ("routine_and_basic_type", "enhanced_type")
                for form in ("ac", "dc")
            ),
        ),
        formulas=(),
        mappings=(),
        decisions=(
            # Tables 2 and 3 are resolved for presence and edition only, so the fixture carries
            # them in their smallest legal shape: their input contract belongs to the DVC
            # guidance service and is exercised by the DVC fixture instead.
            boolean_gate(ids.DVC_VOLTAGE_LIMITS, ("synthetic_input",), ("synthetic_output",)),
            boolean_gate(ids.DVC_PROTECTION_MATRIX, ("synthetic_input",), ("synthetic_output",)),
            partial_discharge_gate,
            foil_gate,
            preconditioning_gate,
            boolean_gate(
                ids.TEST_ASSEMBLED_ROUTINE_EXEMPTION,
                (
                    "sub_assembly_routine_test_performed",
                    "assembly_shown_not_to_compromise_insulation",
                    "assembled_type_test_passed",
                ),
                ("assembled_routine_test_exempt",),
            ),
        ),
        procedures=(
            procedure(
                ids.TEST_WORKING_VOLTAGE_DETERMINATION,
                "working_voltage_determination",
                classifications=("type_test",),
            ),
            *(
                procedure(
                    f"{ids.TEST_IMPULSE_PROCEDURE}.{variant}",
                    "impulse_withstand_voltage",
                    classifications=("type_test", "sample_test"),
                )
                for variant in ("insulation_basic", "insulation_reinforced", "transient_reduction")
            ),
            procedure(
                ids.TEST_PARTIAL_DISCHARGE,
                "partial_discharge",
                applicability_rule_id=partial_discharge_gate.id,
            ),
            procedure(
                ids.TEST_INTERNAL_SPD_MONITORING,
                "internal_spd_monitoring",
                classifications=("type_test",),
            ),
            procedure(
                f"{ids.TEST_PRECONDITIONING}.electrical_tests",
                "electrical_test_preconditioning",
                applicability_rule_id=preconditioning_gate.id,
            ),
            procedure(
                f"{ids.TEST_PRECONDITIONING}.material",
                "material_preconditioning",
                classifications=("type_test",),
                applicability_rule_id=preconditioning_gate.id,
            ),
            procedure(
                ids.TEST_ACCESSIBLE_SURFACE_FOIL,
                "accessible_surface_foil_placement",
                applicability_rule_id=foil_gate.id,
            ),
        ),
        curves=(fault_time_voltage,),
    )


@pytest.fixture
def synthetic_package() -> RulePackage:
    return synthetic_rule_package()


@pytest.fixture
def package_dict(synthetic_package: RulePackage) -> dict[str, object]:
    return synthetic_package.model_dump(mode="json")
