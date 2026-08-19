from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids


def test_catalog_has_thirty_five_unique_ids() -> None:
    """Twenty-six from Issue #34, the band factor Issue #72 made resolvable, the two
    reinforced spacing treatments Issue #110 extracted, the permitted alternative to the
    impulse withstand test that Issue #37 needs the engineer to be able to choose, the
    four subclauses of the AC or DC voltage test whose body nothing else states, and the
    subclause that decides when a solid insulation owes the partial-discharge test."""

    assert len(semantic_ids.REQUIRED_SEMANTIC_IDS) == 35


def test_every_id_uses_the_documented_prefix_and_shape() -> None:
    for value in semantic_ids.REQUIRED_SEMANTIC_IDS:
        assert value.startswith("iec62477_2022.")
        assert value == value.lower()
        assert len(value.split(".")) == 3
        assert " " not in value
