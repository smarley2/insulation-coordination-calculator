from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids


def test_catalog_has_twenty_five_unique_ids() -> None:
    assert len(semantic_ids.REQUIRED_SEMANTIC_IDS) == 25


def test_every_id_uses_the_documented_prefix_and_shape() -> None:
    for value in semantic_ids.REQUIRED_SEMANTIC_IDS:
        assert value.startswith("iec62477_2022.")
        assert value == value.lower()
        assert len(value.split(".")) == 3
        assert " " not in value
