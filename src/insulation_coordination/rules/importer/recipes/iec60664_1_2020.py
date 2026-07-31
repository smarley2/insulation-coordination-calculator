from insulation_coordination.rules.importer.identify import (
    FormulaAuditSpec,
    MappingAuditSpec,
    StandardRecipe,
    TableAuditSpec,
)


def _mapping_specs() -> tuple[MappingAuditSpec, ...]:
    mappings: list[MappingAuditSpec] = []
    for kind in ("functional", "basic", "reinforced"):
        clearance_clause = "5.2.4" if kind == "functional" else "5.2.5"
        for candidate in ("impulse", "periodic"):
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
                        target_rule_id="iec60664-1:clearance-formula",
                        family="part1-clearance",
                        page_number=70,
                        clause="Annex F",
                        table="F.2",
                    )
                )
        creepage_clause = "5.3.4" if kind == "functional" else "5.3.5"
        mappings.append(
            MappingAuditSpec(
                id=f"iec60664-1-map-{len(mappings) + 1:02d}",
                semantic_route=(
                    f"iec60664-1:{creepage_clause}:{kind}_creepage:"
                    "construction=other:pollution=2:material=I"
                ),
                target_rule_id="iec60664-1:creepage-formula",
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
            target_rule_id="iec60664-1:altitude_correction:base=2000m",
            family="part1-altitude",
            page_number=57,
            clause="Annex B",
            table="B.1",
        )
    )
    return tuple(mappings)


# This recipe intentionally contains locators and semantic contracts only. Numeric
# cells and source prose must never become source assets.
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
            data_strategy="numeric_row_major",
            expected_data_rows=152,
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
            semantic_id="iec60664-1-f3",
            source_table="F.3",
            title_anchor="Table F.3",
            page_number=71,
            clause="Annex F",
            target_unit="mm",
            expected_raw_rows=23,
            expected_raw_columns=3,
            expected_bbox=(70.9, 106.8, 524.4, 623.9),
            data_strategy="numeric_row_major",
            expected_data_rows=35,
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
            semantic_id="iec60664-1-f4",
            source_table="F.4",
            title_anchor="Table F.4",
            page_number=72,
            clause="Annex F",
            target_unit="mm",
            expected_raw_rows=20,
            expected_raw_columns=4,
            expected_bbox=(70.9, 106.8, 524.4, 637.9),
            data_strategy="numeric_row_major",
            expected_data_rows=55,
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
            semantic_id="iec60664-1:clearance-formula",
            unit="mm",
            variables=("raw_sequence",),
            expression_shape=(
                "linear_interpolate:iec60664-1-f2(variable:raw_sequence)"
            ),
            page_number=70,
            clause="Annex F",
            table="F.2",
        ),
        FormulaAuditSpec(
            semantic_id="iec60664-1:creepage-formula",
            unit="mm",
            variables=("raw_sequence",),
            expression_shape=(
                "linear_interpolate:iec60664-1-f4(variable:raw_sequence)"
            ),
            page_number=73,
            clause="Annex F",
            table="F.5",
        ),
        FormulaAuditSpec(
            semantic_id="iec60664-1:altitude_correction:base=2000m",
            unit="1",
            variables=("raw_sequence",),
            expression_shape=(
                "linear_interpolate:iec60664-1-f3(variable:raw_sequence)"
            ),
            page_number=57,
            clause="Annex B",
            table="B.1",
        ),
    ),
    mappings=_mapping_specs(),
)
