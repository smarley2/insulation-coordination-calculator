from insulation_coordination.rules.importer.recipes import RECIPES


def test_interpolation_defaults_to_none() -> None:
    from insulation_coordination.rules.importer.identify import TableAuditSpec

    field = TableAuditSpec.model_fields["interpolation"]
    assert field.default == "none"


def test_existing_recipes_declare_their_interpolation_explicitly() -> None:
    for recipe in RECIPES:
        for spec in recipe.tables:
            assert spec.interpolation in ("none", "linear")
    declared = {
        spec.semantic_id: spec.interpolation for recipe in RECIPES for spec in recipe.tables
    }
    assert declared["iec60664-1-f2"] == "linear"
    assert declared["iec60664-1-a2"] == "linear"
