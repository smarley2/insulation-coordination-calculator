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


#: Physical row (within the table-2 segment) whose cells carry the seven frequency
#: bands' axis values; structural, not a licensed value.
_FREQUENCY_BAND_HEADER_ROW = 0


def _frequency_columns() -> tuple[TableColumnSpec, ...]:
    """Table 2's row axis plus its seven frequency-band data columns.

    The band boundaries are licensed table content, so they are read from the
    document's own header row via ``axis_value_source_row`` instead of being
    declared here.
    """
    columns = _columns(
        ("peak_voltage_kv", "peak voltage entering this table", 0, "axis", "kV"),
        ("frequency_30_100_khz_mm", "creepage for frequency band column 1", 1, "data", "mm"),
        ("frequency_200_khz_mm", "creepage for frequency band column 2", 2, "data", "mm"),
        ("frequency_400_khz_mm", "creepage for frequency band column 3", 3, "data", "mm"),
        ("frequency_700_khz_mm", "creepage for frequency band column 4", 4, "data", "mm"),
        ("frequency_1_mhz_mm", "creepage for frequency band column 5", 5, "data", "mm"),
        ("frequency_2_mhz_mm", "creepage for frequency band column 6", 6, "data", "mm"),
        ("frequency_3_mhz_mm", "creepage for frequency band column 7", 7, "data", "mm"),
    )
    return tuple(
        column
        if column.role == "axis"
        else column.model_copy(update={"axis_value_source_row": _FREQUENCY_BAND_HEADER_ROW})
        for column in columns
    )


def _mapping_specs() -> tuple[MappingAuditSpec, ...]:
    mappings: list[MappingAuditSpec] = [
        MappingAuditSpec(
            id="iec60664-4-map-01",
            semantic_route="iec60664-4:frequency_applicability:frequency_hz",
            target_rule_id="iec60664-4-equation-1-critical-frequency",
            family="part4-applicability",
            page_number=21,
            clause="4.3.1",
            figure="Equation (1)",
        ),
        MappingAuditSpec(
            id="iec60664-4-map-02",
            semantic_route="iec60664-4:frequency_factor:frequency_hz",
            target_rule_id="iec60664-4-equation-2-frequency-factor",
            family="part4-frequency-factor",
            page_number=23,
            clause="4.3.1",
            figure="Equation (2)",
        ),
    ]
    for kind in ("functional", "basic", "supplementary", "reinforced"):
        for pollution in (1, 2):
            mappings.append(
                MappingAuditSpec(
                    id=f"iec60664-4-map-{len(mappings) + 1:02d}",
                    semantic_route=(
                        f"iec60664-4:clearance:{kind}:stress=periodic_peak_v:"
                        f"frequency=frequency_hz:pollution={pollution}"
                    ),
                    target_rule_id="iec60664-4:hf-clearance-table",
                    family="part4-clearance",
                    page_number=29,
                    clause="5",
                    table="1",
                )
            )
        for pollution in (1, 2):
            mappings.append(
                MappingAuditSpec(
                    id=f"iec60664-4-map-{len(mappings) + 1:02d}",
                    semantic_route=(
                        f"iec60664-4:creepage:{kind}:stress=periodic_peak_v:"
                        "frequency=frequency_hz:construction=printed_wiring:"
                        f"pollution={pollution}"
                    ),
                    target_rule_id="iec60664-4:hf-creepage-table",
                    family="part4-creepage",
                    page_number=35,
                    clause="5",
                    table="2",
                )
            )
    return tuple(mappings)


# Layout facts and semantic contracts only. Licensed values are extracted locally.
RECIPE = StandardRecipe(
    id="iec60664-4-2005",
    standard="IEC 60664-4",
    edition="2005",
    identity_claim_pattern=r"(?i)(IEC\s*60664-[14]).{0,24}?\b((?:19|20)\d{2})\b",
    expected_page_count=138,
    accepted_page_counts=(144,),
    metadata_identity_fields=("/Title", "/Subject", "/Keywords"),
    metadata_identity_anchors=("IEC 60664-4", "2005"),
    identity_anchors=(
        "IEC 60664-4",
        "Second edition",
        "high-frequency voltage stress",
    ),
    tables=(
        TableAuditSpec(
            semantic_id="iec60664-4-table-1",
            source_table="1",
            title_anchor="Table 1",
            page_number=29,
            clause="5",
            target_unit="mm",
            interpolation="linear",
            expected_raw_rows=10,
            expected_raw_columns=2,
            expected_bbox=(155.9, 123.2, 439.4, 338.2),
            data_strategy="rectangle",
            data_row_start=1,
            data_column_start=0,
            expected_data_rows=8,
            expected_data_columns=2,
            row_axis_id="peak_voltage_kv",
            row_axis_unit="kV",
            column_axis_id="clearance_branch",
            column_axis_unit="1",
            allowed_suffixes=("a", "b"),
            allowed_qualifiers=("up_to",),
            assertions=("strictly_increasing_axes", "raw_value_correspondence"),
            segments=(
                TableSegmentSpec(
                    id="table-1",
                    page_number=29,
                    title_anchor="Table 1",
                    expected_raw_rows=10,
                    expected_raw_columns=2,
                    expected_bbox=(155.9, 123.2, 439.4, 338.2),
                    header_rows=(0,),
                    data_rows=tuple(range(1, 9)),
                    footnote_rows=(9,),
                ),
            ),
            columns=_columns(
                ("peak_voltage_kv", "peak voltage entering this table", 0, "axis", "kV"),
                ("clearance_mm", "clearance on the same row", 1, "data", "mm"),
            ),
        ),
        TableAuditSpec(
            semantic_id="iec60664-4-table-2",
            source_table="2",
            title_anchor="Table 2",
            page_number=35,
            clause="5",
            target_unit="mm",
            interpolation="linear",
            expected_raw_rows=20,
            expected_raw_columns=8,
            expected_bbox=(70.9, 111.8, 524.5, 463.8),
            data_strategy="rectangle",
            data_row_start=1,
            data_column_start=0,
            expected_data_rows=18,
            expected_data_columns=8,
            row_axis_id="peak_voltage_kv",
            row_axis_unit="kV",
            column_axis_id="frequency_hz",
            column_axis_unit="Hz",
            allowed_suffixes=("a", "b"),
            assertions=("strictly_increasing_axes", "raw_value_correspondence"),
            segments=(
                TableSegmentSpec(
                    id="table-2",
                    page_number=35,
                    title_anchor="Table 2",
                    expected_raw_rows=20,
                    expected_raw_columns=8,
                    expected_bbox=(70.9, 111.8, 524.5, 463.8),
                    header_rows=(0,),
                    data_rows=tuple(range(1, 19)),
                    footnote_rows=(19,),
                ),
            ),
            columns=_frequency_columns(),
        ),
    ),
    formulas=(
        FormulaAuditSpec(
            semantic_id="iec60664-4:hf-clearance-table",
            unit="mm",
            variables=("peak_voltage_kv", "clearance_branch"),
            expression_shape="table_select:iec60664-4-table-1(ceiling,exact)",
            page_number=29,
            clause="5",
            table="1",
        ),
        FormulaAuditSpec(
            semantic_id="iec60664-4:hf-creepage-table",
            unit="mm",
            variables=("peak_voltage_kv", "frequency_hz"),
            expression_shape="table_select:iec60664-4-table-2(ceiling,linear)",
            page_number=35,
            clause="5",
            table="2",
        ),
        FormulaAuditSpec(
            semantic_id="iec60664-4-equation-1-critical-frequency",
            unit="MHz",
            variables=("clearance_mm",),
            expression_shape="critical_frequency_inverse_clearance",
            page_number=21,
            clause="4.3.1",
            figure="Equation (1)",
            extract_from_pdf=True,
            expected_bbox=(230.0, 525.0, 540.0, 565.0),
            applicability="field approximately homogeneous; radius criterion satisfied",
        ),
        FormulaAuditSpec(
            semantic_id="iec60664-4-equation-2-frequency-factor",
            unit="percent",
            variables=("frequency_mhz", "critical_frequency_mhz", "minimum_frequency_mhz"),
            expression_shape="linear_frequency_factor",
            page_number=23,
            clause="4.3.1",
            figure="Equation (2)",
            extract_from_pdf=True,
            expected_bbox=(225.0, 440.0, 540.0, 480.0),
            applicability="critical frequency to minimum frequency",
        ),
        FormulaAuditSpec(
            semantic_id="iec60664-4-minimum-frequency",
            unit="MHz",
            variables=(),
            expression_shape="minimum_frequency_statement",
            page_number=21,
            clause="4.3.1",
            figure="Figure A.1",
            extract_from_pdf=True,
            applicability="Equation (2) upper frequency reference",
        ),
        FormulaAuditSpec(
            semantic_id="iec60664-4-radius-criterion",
            unit="bool",
            variables=("radius_mm", "clearance_mm"),
            expression_shape="radius_to_clearance_criterion",
            page_number=21,
            clause="4.3.1",
            figure="Radius criterion",
            extract_from_pdf=True,
            applicability="approximately homogeneous field classification",
        ),
    ),
    mappings=_mapping_specs(),
)
