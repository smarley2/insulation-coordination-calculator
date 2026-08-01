from typing import Literal

from insulation_coordination.rules.importer.identify import (
    FormulaAuditSpec,
    MappingAuditSpec,
    StandardRecipe,
    TableAuditSpec,
    TableColumnSpec,
    TableSegmentSpec,
)

ColumnRole = Literal["axis", "data", "context"]


def _columns(
    *items: tuple[str, str, int, ColumnRole, str],
) -> tuple[TableColumnSpec, ...]:
    return tuple(
        TableColumnSpec(
            semantic_id=semantic_id,
            heading=heading,
            source_column=source_column,
            role=role,
            unit=unit,
        )
        for semantic_id, heading, source_column, role, unit in items
    )


def _mapping_specs() -> tuple[MappingAuditSpec, ...]:
    mappings: list[MappingAuditSpec] = []
    for kind in ("functional", "basic", "reinforced"):
        clearance_clause = "5.2.4" if kind == "functional" else "5.2.5"
        for candidate, target, table in (
            ("impulse", "iec60664-1:f2-clearance", "F.2"),
            ("periodic", "iec60664-1:f8-clearance", "F.8"),
        ):
            for field in (
                "inhomogeneous",
                "homogeneous",
                "approximately_homogeneous",
            ):
                mappings.append(
                    MappingAuditSpec(
                        id=f"iec60664-1-map-{len(mappings) + 1:02d}",
                        semantic_route=(
                            f"iec60664-1:{clearance_clause}:{kind}_clearance:"
                            f"candidate={candidate}:field={field}:pollution=2"
                        ),
                        target_rule_id=target,
                        family="part1-clearance",
                        page_number=70 if table == "F.2" else 76,
                        clause="Annex F",
                        table=table,
                    )
                )
        creepage_clause = "5.3.4" if kind == "functional" else "5.3.5"
        mappings.append(
            MappingAuditSpec(
                id=f"iec60664-1-map-{len(mappings) + 1:02d}",
                semantic_route=(
                    f"iec60664-1:{creepage_clause}:{kind}_creepage:"
                    "construction=printed_wiring:pollution=2"
                ),
                target_rule_id="iec60664-1:f5-pcb-creepage",
                family="part1-creepage",
                page_number=73,
                clause="Annex F",
                table="F.5",
            )
        )
    mappings.append(
        MappingAuditSpec(
            id=f"iec60664-1-map-{len(mappings) + 1:02d}",
            semantic_route="iec60664-1:altitude_correction:base=2000m",
            target_rule_id="iec60664-1:a2-altitude-factor",
            family="part1-altitude",
            page_number=53,
            clause="Annex A",
            table="A.2",
        )
    )
    return tuple(mappings)


# Layout facts only. Licensed numeric cells and prose are extracted locally.
RECIPE = StandardRecipe(
    id="iec60664-1-2020",
    standard="IEC 60664-1",
    edition="2020",
    expected_page_count=171,
    metadata_identity_fields=("/Title", "/Subject", "/Keywords"),
    metadata_identity_anchors=("IEC 60664-1", "2020"),
    identity_anchors=(
        "IEC 60664-1",
        "Edition 3.0 2020-05",
        "low-voltage supply systems",
    ),
    tables=(
        TableAuditSpec(
            semantic_id="iec60664-1-f2",
            source_table="F.2",
            title_anchor="Table F.2",
            page_number=70,
            clause="Annex F",
            target_unit="mm",
            expected_raw_rows=30,
            expected_raw_columns=7,
            expected_bbox=(70.9, 106.8, 524.4, 773.6),
            data_strategy="rectangle",
            data_row_start=3,
            data_column_start=0,
            expected_data_rows=26,
            expected_data_columns=7,
            row_axis_id="impulse_withstand_kv",
            row_axis_unit="kV",
            column_axis_id="clearance_branch",
            column_axis_unit="1",
            allowed_suffixes=("a", "b", "c", "d", "e"),
            assertions=("strictly_increasing_axes", "raw_value_correspondence"),
            segments=(
                TableSegmentSpec(
                    id="f2",
                    page_number=70,
                    title_anchor="Table F.2",
                    expected_raw_rows=30,
                    expected_raw_columns=7,
                    expected_bbox=(70.9, 106.8, 524.4, 773.6),
                    header_rows=(0, 1, 2),
                    data_rows=tuple(range(3, 29)),
                    footnote_rows=(29,),
                ),
            ),
            columns=_columns(
                ("impulse_withstand_kv", "Required impulse withstand voltage", 0, "axis", "kV"),
                ("case_a_pd1_mm", "Case A pollution degree 1", 1, "data", "mm"),
                ("case_a_pd2_mm", "Case A pollution degree 2", 2, "data", "mm"),
                ("case_a_pd3_mm", "Case A pollution degree 3", 3, "data", "mm"),
                ("case_b_pd1_mm", "Case B pollution degree 1", 4, "data", "mm"),
                ("case_b_pd2_mm", "Case B pollution degree 2", 5, "data", "mm"),
                ("case_b_pd3_mm", "Case B pollution degree 3", 6, "data", "mm"),
            ),
        ),
        TableAuditSpec(
            semantic_id="iec60664-1-f5",
            source_table="F.5",
            title_anchor="Table F.5",
            page_number=73,
            clause="Annex F",
            target_unit="mm",
            expected_raw_rows=49,
            expected_raw_columns=10,
            expected_bbox=(70.8, 106.8, 524.5, 737.5),
            data_strategy="rectangle",
            data_row_start=4,
            data_column_start=0,
            expected_data_rows=39,
            expected_data_columns=3,
            row_axis_id="rms_voltage_v",
            row_axis_unit="V",
            column_axis_id="pcb_pollution_branch",
            column_axis_unit="1",
            allowed_suffixes=("a", "b", "c", "d", "e", "f"),
            assertions=("strictly_increasing_axes", "raw_value_correspondence"),
            segments=(
                TableSegmentSpec(
                    id="f5-page-1",
                    page_number=73,
                    title_anchor="Table F.5",
                    expected_raw_rows=30,
                    expected_raw_columns=10,
                    expected_bbox=(70.8, 106.8, 524.5, 737.5),
                    data_rows=tuple(range(4, 30)),
                    header_rows=(0, 1, 2, 3),
                ),
                TableSegmentSpec(
                    id="f5-page-2",
                    page_number=74,
                    title_anchor="Table F.5",
                    expected_raw_rows=19,
                    expected_raw_columns=10,
                    expected_bbox=(70.8, 106.8, 524.5, 712.2),
                    logical_row_offset=26,
                    data_rows=tuple(range(4, 17)),
                    header_rows=(0, 1, 2, 3),
                    note_rows=(17,),
                    footnote_rows=(18,),
                ),
            ),
            columns=_columns(
                ("rms_voltage_v", "Voltage RMS", 0, "axis", "V"),
                ("pcb_pollution_1", "Printed wiring pollution degree 1", 1, "data", "mm"),
                ("pcb_pollution_2", "Printed wiring pollution degree 2", 2, "data", "mm"),
                ("other_pd1", "Other material pollution degree 1", 3, "context", "mm"),
                ("other_pd2_group_i", "Other material PD2 group I", 4, "context", "mm"),
                ("other_pd2_group_ii", "Other material PD2 group II", 5, "context", "mm"),
                ("other_pd2_group_iii", "Other material PD2 group III", 6, "context", "mm"),
                ("other_pd3_group_i", "Other material PD3 group I", 7, "context", "mm"),
                ("other_pd3_group_ii", "Other material PD3 group II", 8, "context", "mm"),
                ("other_pd3_group_iii", "Other material PD3 group III", 9, "context", "mm"),
            ),
        ),
        TableAuditSpec(
            semantic_id="iec60664-1-f8",
            source_table="F.8",
            title_anchor="Table F.8",
            page_number=76,
            clause="Annex F",
            target_unit="mm",
            expected_raw_rows=35,
            expected_raw_columns=3,
            expected_bbox=(70.9, 146.3, 523.8, 768.7),
            data_strategy="rectangle",
            data_row_start=2,
            data_column_start=0,
            expected_data_rows=33,
            expected_data_columns=3,
            row_axis_id="peak_voltage_kv",
            row_axis_unit="kV",
            column_axis_id="field_case",
            column_axis_unit="1",
            allowed_suffixes=("a", "b", "c"),
            assertions=("strictly_increasing_axes", "raw_value_correspondence"),
            segments=(
                TableSegmentSpec(
                    id="f8",
                    page_number=76,
                    title_anchor="Table F.8",
                    expected_raw_rows=35,
                    expected_raw_columns=6,
                    expected_bbox=(70.9, 146.3, 523.8, 768.7),
                    source_columns=(0, 1, 2),
                    header_rows=(0, 1),
                    data_rows=tuple(range(2, 35)),
                ),
            ),
            columns=_columns(
                ("peak_voltage_kv", "Voltage peak value", 0, "axis", "kV"),
                ("case_a_mm", "Case A inhomogeneous field", 1, "data", "mm"),
                ("case_b_mm", "Case B homogeneous field", 2, "data", "mm"),
            ),
        ),
        TableAuditSpec(
            semantic_id="iec60664-1-f9",
            source_table="F.9",
            title_anchor="Table F.9",
            page_number=76,
            clause="Annex F",
            target_unit="mm",
            expected_raw_rows=35,
            expected_raw_columns=2,
            expected_bbox=(70.9, 146.3, 523.8, 768.7),
            data_strategy="rectangle",
            data_row_start=2,
            data_column_start=0,
            expected_data_rows=33,
            expected_data_columns=2,
            row_axis_id="peak_voltage_kv",
            row_axis_unit="kV",
            column_axis_id="partial_discharge_advice",
            column_axis_unit="1",
            allowed_suffixes=("a", "b", "c"),
            assertions=("strictly_increasing_axes", "raw_value_correspondence"),
            segments=(
                TableSegmentSpec(
                    id="f9",
                    page_number=76,
                    title_anchor="Table F.9",
                    expected_raw_rows=35,
                    expected_raw_columns=6,
                    expected_bbox=(70.9, 146.3, 523.8, 768.7),
                    source_columns=(4, 5),
                    header_rows=(0, 1),
                    data_rows=tuple(range(2, 35)),
                    context_cells=((2, 5), (26, 5)),
                ),
            ),
            columns=_columns(
                ("peak_voltage_kv", "Voltage peak value", 4, "axis", "kV"),
                (
                    "partial_discharge_advice",
                    "Case A partial-discharge information",
                    5,
                    "data",
                    "mm",
                ),
            ),
        ),
        TableAuditSpec(
            semantic_id="iec60664-1-a2",
            source_table="A.2",
            title_anchor="Table A.2",
            page_number=53,
            clause="Annex A",
            target_unit="1",
            expected_raw_rows=12,
            expected_raw_columns=3,
            expected_bbox=(127.6, 394.3, 467.8, 607.2),
            data_strategy="rectangle",
            data_row_start=1,
            data_column_start=0,
            expected_data_rows=11,
            expected_data_columns=2,
            row_axis_id="altitude_m",
            row_axis_unit="m",
            column_axis_id="clearance_factor",
            column_axis_unit="1",
            assertions=("strictly_increasing_axes", "raw_value_correspondence"),
            segments=(
                TableSegmentSpec(
                    id="a2",
                    page_number=53,
                    title_anchor="Table A.2",
                    expected_raw_rows=12,
                    expected_raw_columns=3,
                    expected_bbox=(127.6, 394.3, 467.8, 607.2),
                    header_rows=(0,),
                    data_rows=tuple(range(1, 12)),
                ),
            ),
            columns=_columns(
                ("altitude_m", "Altitude", 0, "axis", "m"),
                ("pressure_kpa", "Normal barometric pressure", 1, "context", "kPa"),
                ("clearance_factor", "Multiplication factor for clearances", 2, "data", "1"),
            ),
        ),
    ),
    formulas=(
        FormulaAuditSpec(
            semantic_id="iec60664-1:f2-clearance",
            unit="mm",
            variables=("impulse_withstand_kv", "clearance_branch"),
            expression_shape="table_select:iec60664-1-f2(ceiling,exact)",
            page_number=70,
            clause="Annex F",
            table="F.2",
        ),
        FormulaAuditSpec(
            semantic_id="iec60664-1:f8-clearance",
            unit="mm",
            variables=("peak_voltage_kv", "field_case"),
            expression_shape="table_select:iec60664-1-f8(ceiling,exact)",
            page_number=76,
            clause="Annex F",
            table="F.8",
        ),
        FormulaAuditSpec(
            semantic_id="iec60664-1:f5-pcb-creepage",
            unit="mm",
            variables=("rms_voltage_v", "pcb_pollution_branch"),
            expression_shape="table_select:iec60664-1-f5(linear,exact)",
            page_number=73,
            clause="Annex F",
            table="F.5",
        ),
        FormulaAuditSpec(
            semantic_id="iec60664-1:a2-altitude-factor",
            unit="1",
            variables=("altitude_m", "clearance_factor"),
            expression_shape="table_select:iec60664-1-a2(linear,exact)",
            page_number=53,
            clause="Annex A",
            table="A.2",
        ),
    ),
    mappings=_mapping_specs(),
)
