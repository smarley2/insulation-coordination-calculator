"""Source-only curve import creates manual review slots. Synthetic only."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pypdf import PdfWriter

from insulation_coordination.domain.rules import SourceReference
from insulation_coordination.rules.importer.curves import RawFigure
from insulation_coordination.rules.importer.extract import _extract_curve_artifacts
from insulation_coordination.rules.importer.identify import StandardIdentity
from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import RECIPE

SOURCE = SourceReference(
    document_id="synthetic-curves",
    standard="SYNTHETIC",
    edition="1",
    page=54,
    figure="SF-5",
)
IDENTITY = StandardIdentity(
    standard="SYNTHETIC",
    edition="1",
    sha256="9" * 64,
    page_count=56,
    recipe_id="synthetic-curves",
)


def _figure(figure: str, page: int, digest: str) -> RawFigure:
    return RawFigure(
        source=SOURCE.model_copy(update={"figure": figure, "page": page}),
        source_mode="vector_path",
        source_bbox=(Decimal(70), Decimal(120), Decimal(524), Decimal(700)),
        pixel_size=None,
        transform=(
            Decimal(1),
            Decimal(0),
            Decimal(0),
            Decimal(1),
            Decimal(0),
            Decimal(0),
        ),
        artifact_sha256=digest,
    )


def test_curve_import_creates_source_figures_and_manual_review_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "synthetic-56-pages.pdf"
    writer = PdfWriter()
    for _ in range(56):
        writer.add_blank_page(width=612, height=792)
    with path.open("wb") as stream:
        writer.write(stream)

    artifacts = {"5": "a" * 64, "6": "b" * 64, "7": "c" * 64}

    def fake_extract(_reader_page, _plumber_page, spec, identity):
        return _figure(spec.figure, spec.page_number, artifacts[spec.figure]).model_copy(
            update={
                "source": SOURCE.model_copy(
                    update={
                        "document_id": identity.recipe_id,
                        "standard": identity.standard,
                        "edition": identity.edition,
                        "page": spec.page_number,
                        "figure": spec.figure,
                    }
                )
            }
        )

    monkeypatch.setattr(
        "insulation_coordination.rules.importer.curves.extract_raw_figure", fake_extract
    )
    figures, curves, proposals, review_items = _extract_curve_artifacts(
        path, IDENTITY.model_copy(update={"recipe_id": "iec62477-1-2022"}), RECIPE
    )

    assert len(figures) == 3
    assert curves == ()
    assert proposals == ()
    assert len(review_items) == 8
    assert all(item.code == "CURVE_VARIANT_REVIEW_REQUIRED" for item in review_items)
