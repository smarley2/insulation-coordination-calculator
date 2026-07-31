from insulation_coordination.rules.importer.identify import (
    FormulaAuditSpec,
    MappingAuditSpec,
    StandardRecipe,
    TableAuditSpec,
)


def _mapping_specs() -> tuple[MappingAuditSpec, ...]:
    mappings = [
        MappingAuditSpec(
            id="iec60664-4-map-01",
            semantic_route="iec60664-4:functional_applicability:stress=periodic_peak_v:frequency=frequency_hz",
            target_rule_id="iec60664-4:functional-applicability-formula",
            family="part4-applicability",
            page_number=29,
            clause="5",
            table="1",
        ),
        MappingAuditSpec(
            id="iec60664-4-map-02",
            semantic_route="iec60664-4:field_iteration:tolerance",
            target_rule_id="iec60664-4:iteration-tolerance-formula",
            family="part4-iteration",
            page_number=35,
            clause="5",
            table="2",
        ),
        MappingAuditSpec(
            id="iec60664-4-map-03",
            semantic_route="iec60664-4:field_iteration:max_iterations",
            target_rule_id="iec60664-4:iteration-limit-formula",
            family="part4-iteration",
            page_number=35,
            clause="5",
            table="2",
        ),
    ]
    for field in ("homogeneous", "approximately_homogeneous"):
        mappings.extend(
            (
                MappingAuditSpec(
                    id=f"iec60664-4-map-{len(mappings) + 1:02d}",
                    semantic_route=f"iec60664-4:critical_frequency:field={field}",
                    target_rule_id="iec60664-4:critical-frequency-formula",
                    family="part4-critical-frequency",
                    page_number=35,
                    clause="5",
                    table="2",
                ),
                MappingAuditSpec(
                    id=f"iec60664-4-map-{len(mappings) + 2:02d}",
                    semantic_route=f"iec60664-4:radius_criterion:field={field}",
                    target_rule_id="iec60664-4:radius-criterion-formula",
                    family="part4-radius",
                    page_number=35,
                    clause="5",
                    table="2",
                ),
            )
        )
    for kind in ("functional", "basic", "reinforced"):
        for field in (
            "inhomogeneous",
            "homogeneous",
            "approximately_homogeneous",
        ):
            mappings.append(
                MappingAuditSpec(
                    id=f"iec60664-4-map-{len(mappings) + 1:02d}",
                    semantic_route=(
                        f"iec60664-4:clearance:{kind}:stress=periodic_peak_v:"
                        f"frequency=frequency_hz:field={field}:pollution=2"
                    ),
                    target_rule_id="iec60664-4:hf-clearance-formula",
                    family="part4-clearance",
                    page_number=35,
                    clause="5",
                    table="2",
                )
            )
        mappings.append(
            MappingAuditSpec(
                id=f"iec60664-4-map-{len(mappings) + 1:02d}",
                semantic_route=(
                    f"iec60664-4:creepage:{kind}:stress=periodic_peak_v:"
                    "frequency=frequency_hz:construction=other:"
                    "pollution=2:material=I"
                ),
                target_rule_id="iec60664-4:hf-creepage-formula",
                family="part4-creepage",
                page_number=95,
                clause="6",
                table="5",
            )
        )
    return tuple(mappings)


# Public recipe data is limited to stable document anchors and semantic contracts.
RECIPE = StandardRecipe(
    id="iec60664-4-2005",
    standard="IEC 60664-4",
    edition="2005",
    expected_page_count=144,
    metadata_identity_fields=("/Title", "/Subject", "/Keywords"),
    metadata_identity_anchors=("IEC 60664-4", "2005"),
    identity_anchors=(
        "IEC 60664-4",
        "first edition",
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
            expected_raw_rows=10,
            expected_raw_columns=2,
            expected_bbox=(155.9, 123.2, 439.4, 338.2),
            data_strategy="numeric_row_major",
            expected_data_rows=15,
            expected_data_columns=1,
            row_axis_id="raw_sequence",
            row_axis_unit="1",
            column_axis_id="value_branch",
            column_axis_unit="1",
            assertions=(
                "complete_grid",
                "strictly_increasing_axes",
                "raw_value_correspondence",
            ),
        ),
        TableAuditSpec(
            semantic_id="iec60664-4-table-2",
            source_table="2",
            title_anchor="Table 2",
            page_number=35,
            clause="5",
            target_unit="mm",
            expected_raw_rows=20,
            expected_raw_columns=8,
            expected_bbox=(70.9, 111.8, 524.5, 463.8),
            data_strategy="numeric_row_major",
            expected_data_rows=79,
            expected_data_columns=1,
            row_axis_id="raw_sequence",
            row_axis_unit="1",
            column_axis_id="value_branch",
            column_axis_unit="1",
            assertions=(
                "complete_grid",
                "strictly_increasing_axes",
                "raw_value_correspondence",
            ),
        ),
        TableAuditSpec(
            semantic_id="iec60664-4-table-5",
            source_table="5",
            title_anchor="Table 5",
            page_number=95,
            clause="6",
            target_unit="mm",
            expected_raw_rows=6,
            expected_raw_columns=4,
            expected_bbox=(67.3, 591.4, 528.0, 686.6),
            anchor_max_vertical_gap=120.0,
            data_strategy="numeric_row_major",
            expected_data_rows=20,
            expected_data_columns=1,
            row_axis_id="raw_sequence",
            row_axis_unit="1",
            column_axis_id="value_branch",
            column_axis_unit="1",
            assertions=(
                "complete_grid",
                "strictly_increasing_axes",
                "raw_value_correspondence",
            ),
        ),
    ),
    formulas=(
        FormulaAuditSpec(
            semantic_id="iec60664-4:hf-clearance-formula",
            unit="mm",
            variables=("raw_sequence",),
            expression_shape=(
                "linear_interpolate:iec60664-4-table-1(variable:raw_sequence)"
            ),
            page_number=29,
            clause="5",
            table="1",
        ),
        FormulaAuditSpec(
            semantic_id="iec60664-4:hf-creepage-formula",
            unit="mm",
            variables=("raw_sequence",),
            expression_shape=(
                "linear_interpolate:iec60664-4-table-5(variable:raw_sequence)"
            ),
            page_number=95,
            clause="6",
            table="5",
        ),
        FormulaAuditSpec(
            semantic_id="iec60664-4:critical-frequency-formula",
            unit="Hz",
            variables=("raw_sequence",),
            expression_shape=(
                "linear_interpolate:iec60664-4-table-2(variable:raw_sequence)"
            ),
            page_number=35,
            clause="5",
            table="2",
        ),
        FormulaAuditSpec(
            semantic_id="iec60664-4:radius-criterion-formula",
            unit="bool",
            variables=("radius_mm", "clearance_mm"),
            expression_shape=(
                "compare(divide(variable:radius_mm,variable:clearance_mm),literal)"
            ),
            page_number=35,
            clause="5",
            table="2",
        ),
        FormulaAuditSpec(
            semantic_id="iec60664-4:functional-applicability-formula",
            unit="bool",
            variables=(),
            expression_shape="compare(literal,literal)",
            page_number=29,
            clause="5",
            table="1",
        ),
        FormulaAuditSpec(
            semantic_id="iec60664-4:iteration-tolerance-formula",
            unit="mm",
            variables=(),
            expression_shape="lookup:iec60664-4-table-2(literal,literal)",
            page_number=35,
            clause="5",
            table="2",
        ),
        FormulaAuditSpec(
            semantic_id="iec60664-4:iteration-limit-formula",
            unit="iterations",
            variables=(),
            expression_shape="lookup:iec60664-4-table-2(literal,literal)",
            page_number=35,
            clause="5",
            table="2",
        ),
    ),
    mappings=_mapping_specs(),
)
