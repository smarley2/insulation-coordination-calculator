"""Identification must fail closed on a malformed document, not raise the PDF layer's error.

The maintainer picks the file, and a standards folder holds unrelated documents, so a
document whose font, page tree, or object references are incomplete has to come back as a
refusal the Rule Manager can show.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from insulation_coordination.rules.importer.identify import (
    StandardIdentificationError,
    identify_standard,
)


def _pdf_with_an_incomplete_composite_font(path: Path) -> Path:
    """A structurally valid PDF whose Type0 font omits its descendant font entry.

    ``_add_object`` is pypdf's only way to create the indirect references a font
    resource needs; the library exposes no public equivalent.
    """
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)

    font = DictionaryObject()
    font[NameObject("/Type")] = NameObject("/Font")
    font[NameObject("/Subtype")] = NameObject("/Type0")
    font[NameObject("/BaseFont")] = NameObject("/Incomplete")
    font[NameObject("/Encoding")] = NameObject("/Identity-H")

    fonts = DictionaryObject()
    fonts[NameObject("/F1")] = writer._add_object(font)
    resources = DictionaryObject()
    resources[NameObject("/Font")] = fonts
    page[NameObject("/Resources")] = resources

    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 10 100 Td <0041> Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)

    with path.open("wb") as handle:
        writer.write(handle)
    return path


def test_the_fixture_reproduces_the_pdf_layer_failure(tmp_path: Path) -> None:
    """Guard the fixture itself: without this, the test below could pass vacuously."""

    broken = _pdf_with_an_incomplete_composite_font(tmp_path / "incomplete-font.pdf")
    with pytest.raises(KeyError):
        PdfReader(broken).pages[0].extract_text()


def test_a_pdf_with_an_incomplete_font_is_refused(tmp_path: Path) -> None:
    broken = _pdf_with_an_incomplete_composite_font(tmp_path / "incomplete-font.pdf")
    with pytest.raises(StandardIdentificationError):
        identify_standard(broken)
