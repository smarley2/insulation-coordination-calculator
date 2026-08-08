from datetime import UTC, datetime
from decimal import Decimal

import pytest

from insulation_coordination.domain.rules import (
    RULE_SCHEMA_VERSION,
    Add,
    ApprovalRecord,
    Compare,
    CompatibilityMapping,
    DecisionInput,
    DecisionOutput,
    DecisionRow,
    DecisionRule,
    DecisionValue,
    Divide,
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
    Variable,
)


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
        tables=tables,
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


@pytest.fixture
def synthetic_package() -> RulePackage:
    return synthetic_rule_package()


@pytest.fixture
def package_dict(synthetic_package: RulePackage) -> dict[str, object]:
    return synthetic_package.model_dump(mode="json")
