from insulation_coordination.rules.importer.identify import (
    FormulaAuditSpec,
    MappingAuditSpec,
    StandardRecipe,
    TableAuditSpec,
)


def _mapping_specs() -> tuple[MappingAuditSpec, ...]:
    mappings = [
        MappingAuditSpec(
            "iec60664-4:functional_applicability:stress=periodic_peak_v:frequency=frequency_hz",
            "part4-applicability",
            29,
            "5",
            table="1",
        ),
        MappingAuditSpec(
            "iec60664-4:field_iteration:tolerance",
            "part4-iteration",
            35,
            "5",
            table="2",
        ),
        MappingAuditSpec(
            "iec60664-4:field_iteration:max_iterations",
            "part4-iteration",
            35,
            "5",
            table="2",
        ),
    ]
    for field in ("homogeneous", "approximately_homogeneous"):
        mappings.extend(
            (
                MappingAuditSpec(
                    f"iec60664-4:critical_frequency:field={field}",
                    "part4-critical-frequency",
                    35,
                    "5",
                    table="2",
                ),
                MappingAuditSpec(
                    f"iec60664-4:radius_criterion:field={field}",
                    "part4-radius",
                    35,
                    "5",
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
                    (
                        f"iec60664-4:clearance:{kind}:stress=periodic_peak_v:"
                        f"frequency=frequency_hz:field={field}:pollution=2"
                    ),
                    "part4-clearance",
                    35,
                    "5",
                    table="2",
                )
            )
        mappings.append(
            MappingAuditSpec(
                (
                    f"iec60664-4:creepage:{kind}:stress=periodic_peak_v:"
                    "frequency=frequency_hz:construction=other:"
                    "pollution=2:material=I"
                ),
                "part4-creepage",
                95,
                "6",
                table="5",
            )
        )
    return tuple(mappings)


# Public recipe data is limited to stable document anchors and semantic contracts.
RECIPE = StandardRecipe(
    id="iec60664-4-2005",
    standard="IEC 60664-4",
    edition="2005",
    metadata_keys=("/CreationDate", "/Producer"),
    identity_anchors=(
        "IEC 60664-4",
        "first edition",
        "high-frequency voltage stress",
    ),
    tables=(
        TableAuditSpec(
            "iec60664-4-table-1",
            "1",
            29,
            "5",
            "mm",
            10,
            2,
            (155.9, 123.2, 439.4, 338.2),
        ),
        TableAuditSpec(
            "iec60664-4-table-2",
            "2",
            35,
            "5",
            "mm",
            20,
            8,
            (70.9, 111.8, 524.5, 463.8),
        ),
        TableAuditSpec(
            "iec60664-4-table-5",
            "5",
            95,
            "6",
            "mm",
            6,
            4,
            (67.3, 591.4, 528.0, 686.6),
        ),
    ),
    formulas=(
        FormulaAuditSpec("iec60664-4:hf-clearance-formula", "mm", 29, "5", table="1"),
        FormulaAuditSpec("iec60664-4:hf-creepage-formula", "mm", 95, "6", table="5"),
        FormulaAuditSpec(
            "iec60664-4:critical-frequency-formula",
            "Hz",
            35,
            "5",
            table="2",
        ),
        FormulaAuditSpec(
            "iec60664-4:radius-criterion-formula",
            "bool",
            35,
            "5",
            table="2",
        ),
    ),
    mappings=_mapping_specs(),
)
