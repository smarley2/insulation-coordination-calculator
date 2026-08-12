"""Human-readable labels shared by UI and report presentation code."""

from __future__ import annotations

from collections.abc import Sequence

from insulation_coordination.domain.project import PairCase, Project

#: This application's own statement of scope for the on-board-charger (OBC) worked
#: example: IEC 62477-1:2022 does not cover EV/OBC equipment, so the OBC example is a
#: topology illustration only, never a claim of compliance. Kept as one constant so
#: every place the OBC example appears - a guidance example in
#: :mod:`insulation_coordination.ui.topology_guidance`, or the example project's own
#: domain descriptions in ``tests/fixtures/topology_examples.py`` - carries the
#: identical wording rather than a paraphrase that could drift from it. Lives here,
#: not in the UI package, so a test fixture can use it without importing ``ui``.
OBC_APPLICABILITY_WARNING = (
    "OBC is a topology example only. IEC 62477-1:2022 excludes electric-vehicle "
    "electrical equipment/systems; the applicable EV/OBC product standard takes "
    "precedence."
)

_COMPARISON_SYMBOLS = {
    "lt": "<",
    "le": "<=",
    "eq": "==",
    "ne": "!=",
    "ge": ">=",
    "gt": ">",
}
_AXIS_MODES = {
    "exact": "exact match",
    "ceiling": "next value up",
    "linear": "interpolated",
}


def render_expression(expression: object) -> str:
    """Render a typed rule expression as ordinary arithmetic a reviewer can check.

    The audit trail needs the node tree; a human reading the screen needs
    ``0.2 / clearance_mm`` and the name of the table a value is read from.
    """
    node = expression.model_dump(mode="python") if hasattr(expression, "model_dump") else expression
    if not isinstance(node, dict):
        return str(expression)
    operation = str(node.get("op", "?"))
    if operation == "literal":
        return str(node["value"])
    if operation == "variable":
        return str(node["name"])
    if operation in {"add", "multiply"}:
        separator = " + " if operation == "add" else " * "
        return f"({separator.join(render_expression(item) for item in node['operands'])})"
    if operation in {"minimum", "maximum"}:
        operands = ", ".join(render_expression(item) for item in node["operands"])
        return f"{operation}({operands})"
    if operation == "divide":
        return (
            f"({render_expression(node['numerator'])} / {render_expression(node['denominator'])})"
        )
    if operation == "compare":
        symbol = _COMPARISON_SYMBOLS.get(str(node["comparison"]), str(node["comparison"]))
        return f"{render_expression(node['left'])} {symbol} {render_expression(node['right'])}"
    if operation == "select":
        return (
            f"if {render_expression(node['condition'])} "
            f"then {render_expression(node['if_true'])} "
            f"else {render_expression(node['if_false'])}"
        )
    if operation == "round":
        return f"round({render_expression(node['value'])}, {node['places']}, {node['mode']})"
    if operation == "lookup":
        return (
            f"table {node['table_id']}[row {render_expression(node['row'])}, "
            f"column {render_expression(node['column'])}]"
        )
    if operation == "linear_interpolate":
        column = node.get("column")
        target = f", column {render_expression(column)}" if column is not None else ""
        return f"table {node['table_id']}[interpolate {render_expression(node['x'])}{target}]"
    if operation == "table_select":
        row_mode = _AXIS_MODES.get(str(node["row_mode"]), str(node["row_mode"]))
        column_mode = _AXIS_MODES.get(str(node["column_mode"]), str(node["column_mode"]))
        return (
            f"table {node['table_id']}"
            f"[row {render_expression(node['row'])} ({row_mode}), "
            f"column {render_expression(node['column'])} ({column_mode})]"
        )
    if operation == "power":
        base = render_expression(node["base"])
        if isinstance(node["base"], dict) and node["base"].get("op") == "power":
            base = f"({base})"
        return f"{base} ^ ({node['numerator']}/{node['denominator']})"
    return operation


def pair_label(project: Project, pair: PairCase) -> str:
    """Return the stable human label for a pair's two net classes."""
    names_by_id = {net_class.id: net_class.name for net_class in project.net_classes}
    return f"{names_by_id.get(pair.net_a, '?')} ↔ {names_by_id.get(pair.net_b, '?')}"


def group_label(project: Project, pair_ids: Sequence[object], index: int) -> str:
    """Return the human label for one calculation group, without internal identifiers."""
    pairs_by_id = {str(pair.id): pair for pair in project.pairs}
    members = ", ".join(
        pair_label(project, pairs_by_id[str(pair_id)])
        for pair_id in pair_ids
        if str(pair_id) in pairs_by_id
    )
    count = len(pair_ids)
    label = f"Group {index} — {count} pair{'s' if count != 1 else ''}"
    return f"{label}: {members}" if members else label
