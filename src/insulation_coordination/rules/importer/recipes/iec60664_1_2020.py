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
                        (
                            f"iec60664-1:{clearance_clause}:{kind}_clearance:"
                            f"candidate={candidate}:field={field}:pollution=2"
                        ),
                        "part1-clearance",
                        70,
                        "Annex F",
                        table="F.2",
                    )
                )
        creepage_clause = "5.3.4" if kind == "functional" else "5.3.5"
        mappings.append(
            MappingAuditSpec(
                (
                    f"iec60664-1:{creepage_clause}:{kind}_creepage:"
                    "construction=other:pollution=2:material=I"
                ),
                "part1-creepage",
                73,
                "Annex F",
                table="F.5",
            )
        )
    mappings.append(
        MappingAuditSpec(
            "iec60664-1:altitude_correction:base=2000m",
            "part1-altitude",
            57,
            "Annex B",
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
    metadata_keys=("/CreationDate", "/Producer"),
    identity_anchors=(
        "IEC 60664-1",
        "Edition 3.0 2020-05",
        "low-voltage supply systems",
    ),
    tables=(
        TableAuditSpec(
            "iec60664-1-f2",
            "F.2",
            70,
            "Annex F",
            "mm",
            30,
            7,
            (70.9, 106.8, 524.4, 773.6),
        ),
        TableAuditSpec(
            "iec60664-1-f3",
            "F.3",
            71,
            "Annex F",
            "mm",
            23,
            3,
            (70.9, 106.8, 524.4, 623.9),
        ),
        TableAuditSpec(
            "iec60664-1-f4",
            "F.4",
            72,
            "Annex F",
            "mm",
            20,
            4,
            (70.9, 106.8, 524.4, 637.9),
        ),
    ),
    formulas=(
        FormulaAuditSpec(
            "iec60664-1:clearance-formula",
            "mm",
            70,
            "Annex F",
            table="F.2",
        ),
        FormulaAuditSpec(
            "iec60664-1:creepage-formula",
            "mm",
            73,
            "Annex F",
            table="F.5",
        ),
        FormulaAuditSpec(
            "iec60664-1:altitude_correction:base=2000m",
            "1",
            57,
            "Annex B",
            table="B.1",
        ),
    ),
    mappings=_mapping_specs(),
)
