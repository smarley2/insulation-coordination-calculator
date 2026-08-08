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
    return f"BT /F1 9 Tf {x:.1f} {y:.1f} Td (".encode() + _pdf_string(value) + b") Tj ET"


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


def create_clause_pdf(path: Path) -> None:
    """Three-page synthetic document with a two-bullet clause fragment on page 3.

    Neutral content only: no IEC wording, values, or structure. Page 3 carries a
    two-bullet list inside the clause bbox (one bullet wraps across two physical
    lines) plus a decoy line outside the bbox.
    """

    writer = PdfWriter()
    for page_index in range(3):
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
        commands: list[bytes] = []
        if page_index == 2:
            # pdfplumber "top" coordinates: page height minus PDF y. Bbox top 300
            # to bottom 700 -> PDF y 492 down to 92. Decoy at top 720 (y 72).
            commands = [
                _text_command(80, 480, "SYMBOL first neutral condition not exceeding 30 s"),
                _text_command(80, 460, "SYMBOL second neutral condition with a wrapped"),
                _text_command(96, 444, "line that continues here and references the curve slot"),
                _text_command(80, 72, "SYMBOL outside decoy line not exceeding 99 s"),
            ]
        else:
            commands = [_text_command(72, 700, f"synthetic filler page {page_index + 1}")]
        stream = DecodedStreamObject()
        stream.set_data(b"\n".join(commands))
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_metadata(
        {
            "/Title": "synthetic clause fixture",
            "/ICC-Synthetic": "true",
        }
    )
    with path.open("wb") as target:
        writer.write(target)


def create_curve_source_pdf(path: Path) -> None:
    """Two-page synthetic curve-source fixture. No IEC content.

    Page 1 (pdfplumber page): vector path commands plus one lossless image inside the
    curve bbox (70, 200)-(400, 500). Page 2: one lossless image only. Coordinates are
    pdfplumber "top" space; PDF y = 792 - top.
    """

    import zlib

    from pypdf.generic import NumberObject

    writer = PdfWriter()

    def _image_ref(name: str) -> object:
        from PIL import Image

        raw = Image.new("L", (8, 8), color=64).tobytes()
        xobj = DecodedStreamObject()
        xobj.set_data(zlib.compress(raw))
        xobj.update(
            {
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(8),
                NameObject("/Height"): NumberObject(8),
                NameObject("/ColorSpace"): NameObject("/DeviceGray"),
                NameObject("/BitsPerComponent"): NumberObject(8),
                NameObject("/Filter"): NameObject("/FlateDecode"),
            }
        )
        return writer._add_object(xobj)

    for page_index in range(2):
        page = writer.add_blank_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
        ref = _image_ref("Im1")
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/XObject"): DictionaryObject({NameObject("/Im1"): ref}),
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
                ),
            }
        )
        # Bbox (70,200)-(400,500) top-space -> PDF x 70..400, y 292..592.
        image_cmd = b"q 40 0 0 40 100 350 cm /Im1 Do Q"
        if page_index == 0:
            commands = [
                image_cmd,
                b"1.5 w",
                b"100 400 m 200 450 l 300 500 l S",
                b"0.8 w",
                b"120 380 m 220 420 l S",
            ]
        else:
            commands = [image_cmd]
        stream = DecodedStreamObject()
        stream.set_data(b"\n".join(commands))
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_metadata(
        {
            "/Title": "synthetic curve source fixture",
            "/ICC-Synthetic": "true",
        }
    )
    with path.open("wb") as target:
        writer.write(target)
