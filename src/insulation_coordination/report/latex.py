"""Deterministic LaTeX renderer with explicit text/formula trust separation."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from insulation_coordination.domain.rules import SourceReference
from insulation_coordination.report.human_view import build_human_report_view
from insulation_coordination.report.model import ReportModel

_TEMPLATE_DIR = Path(__file__).with_name("templates")
_ESCAPES = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "%": r"\%",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def render_latex(model: ReportModel) -> str:
    """Render one complete document without mutating the report snapshot."""
    environment = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters.update(
        tex=escape_latex_text,
        value=_value,
        reference=_reference,
        yesno=lambda value: "yes" if value else "no",
    )
    return environment.get_template("report.tex.j2").render(
        model=model,
        human=build_human_report_view(model),
    )


def escape_latex_text(value: object) -> str:
    """Escape untrusted text; formula fields never pass through this function."""
    return "".join(_ESCAPES.get(character, character) for character in str(value))


def _value(value: object) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, Decimal):
        return format(value, "f")
    if hasattr(value, "value"):
        return escape_latex_text(value.value)
    return escape_latex_text(value)


def _reference(reference: SourceReference | None) -> str:
    if reference is None:
        return "Engine aggregation; no table content reproduced"
    parts = [f"{reference.standard} ({reference.edition})"]
    if reference.clause:
        parts.append(reference.clause)
    if reference.table:
        parts.append(f"Table {reference.table}")
    if reference.figure:
        parts.append(f"Figure {reference.figure}")
    if reference.note:
        parts.append(f"Note {reference.note}")
    if reference.row:
        parts.append(f"row {reference.row}")
    if reference.column:
        parts.append(f"column {reference.column}")
    return escape_latex_text(", ".join(parts))


def breakable_latex_text(value: object) -> str:
    """Escape text and allow line breaks inside long unbreakable runs.

    Chunking happens before escaping so a break can never land inside an
    escape sequence such as ``\\textbackslash{}``.
    """
    text = str(value)
    return r"\allowbreak{}".join(
        escape_latex_text(text[index : index + 12]) for index in range(0, len(text), 12)
    )
