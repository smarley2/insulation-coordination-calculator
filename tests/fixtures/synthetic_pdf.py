"""Synthetic PDF geometry fixtures. Contains no IEC content of any kind."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

_PAGE_WIDTH = 612
_PAGE_HEIGHT = 792
_TABLE_BBOX = (72.0, 192.0, 252.0, 312.0)
_CELLS = (
    ("axis", "10", "20"),
    ("1", "1.1", "1.2"),
    ("2", "2.1", "2.2"),
)


def _pdf_string(value: str) -> bytes:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1")


def _text_command(x: float, y: float, value: str) -> bytes:
    return f"BT /F1 9 Tf {x:.1f} {y:.1f} Td (".encode() + _pdf_string(
        value
    ) + b") Tj ET"


def _table_commands(
    bbox: tuple[float, float, float, float],
    cells: tuple[tuple[str, ...], ...],
) -> list[bytes]:
    x0, top, x1, bottom = bbox
    rows = len(cells)
    columns = len(cells[0])
    pdf_top = _PAGE_HEIGHT - top
    pdf_bottom = _PAGE_HEIGHT - bottom
    row_height = (pdf_top - pdf_bottom) / rows
    column_width = (x1 - x0) / columns
    commands = [b"0.7 w"]
    for column in range(columns + 1):
        x = x0 + column * column_width
        commands.append(f"{x:.1f} {pdf_bottom:.1f} m {x:.1f} {pdf_top:.1f} l S".encode())
    for row in range(rows + 1):
        y = pdf_bottom + row * row_height
        commands.append(f"{x0:.1f} {y:.1f} m {x1:.1f} {y:.1f} l S".encode())
    for row, values in enumerate(cells):
        for column, value in enumerate(values):
            x = x0 + column * column_width + 5
            y = pdf_top - (row + 1) * row_height + row_height / 2 - 3
            commands.append(_text_command(x, y, value))
    return commands


def create_geometry_pdf(
    path: Path,
    *,
    standard: str,
    edition: str,
    edition_anchor: str,
    topic_anchor: str,
    table_anchor: str,
    cells: tuple[tuple[str, ...], ...] = _CELLS,
    metadata: dict[str, str] | None = None,
    second_table: bool = False,
) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/F1"): DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica"),
                        }
                    )
                }
            )
        }
    )
    commands = [
        _text_command(72, 750, standard),
        _text_command(72, 734, edition_anchor),
        _text_command(72, 718, topic_anchor),
        _text_command(72, 616, table_anchor),
        *_table_commands(_TABLE_BBOX, cells),
    ]
    if second_table:
        second_bbox = (300.0, 192.0, 480.0, 312.0)
        commands.extend(
            (
                _text_command(300, 616, table_anchor),
                *_table_commands(second_bbox, cells),
            )
        )
    stream = DecodedStreamObject()
    stream.set_data(b"\n".join(commands))
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_metadata(
        {
            "/Title": f"{standard}:{edition} synthetic geometry fixture",
            "/ICC-Synthetic": "true",
            **(metadata or {}),
        }
    )
    with path.open("wb") as target:
        writer.write(target)
