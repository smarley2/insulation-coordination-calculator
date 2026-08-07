import re

from insulation_coordination.rules.importer.recipes import RECIPES

# Matches a table_select expression_shape such as "table_select:some-id(linear,exact)".
# Formulas whose expression_shape does not match (equation contracts like
# "critical_frequency_inverse_clearance") do not target a table and are skipped.
_TABLE_SELECT = re.compile(
    r"^table_select:(?P<table_id>.+)\((?P<row_mode>[a-z]+),(?P<column_mode>[a-z]+)\)$"
)


def test_interpolation_defaults_to_none() -> None:
    from insulation_coordination.rules.importer.identify import TableAuditSpec

    field = TableAuditSpec.model_fields["interpolation"]
    assert field.default == "none"


def test_every_linear_row_or_column_selection_targets_an_interpolable_table() -> None:
    """A formula selecting with a linear row/column mode must target an interpolable table.

    Package validation already enforces this invariant on built domain objects; this walks
    every recipe's raw audit specs so a violation is caught at recipe-authoring time instead
    of surfacing only when a draft is approved.
    """
    tables_by_id = {spec.semantic_id: spec for recipe in RECIPES for spec in recipe.tables}
    saw_linear_selection = False
    saw_none_table = False
    for recipe in RECIPES:
        for formula in recipe.formulas:
            match = _TABLE_SELECT.match(formula.expression_shape)
            if match is None:
                continue
            table = tables_by_id[match["table_id"]]
            selects_linearly = "linear" in (match["row_mode"], match["column_mode"])
            if selects_linearly:
                saw_linear_selection = True
                assert table.interpolation == "linear", (
                    f"{formula.semantic_id} selects {match['table_id']} with a linear "
                    "mode, but that table does not declare interpolation='linear'"
                )
            if table.interpolation == "none":
                saw_none_table = True
                assert not selects_linearly, (
                    f"{formula.semantic_id} selects {match['table_id']} with a linear "
                    "mode even though that table declares interpolation='none'"
                )
    # Guard against the walk silently checking nothing if the recipes ever stop
    # exercising both sides of the invariant.
    assert saw_linear_selection
    assert saw_none_table
