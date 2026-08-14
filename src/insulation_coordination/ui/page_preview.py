"""Zoomable, pannable view of the source pages a reviewed artifact was read from.

Runtime display from the maintainer's own licensed PDF, never anything written down: a reviewer
judging an extracted cell or interpreting a clause statement has to see the print it came from.
Extracted from the raw grid review dialog, which grew this pane first, so the clause fact dialog
gets the same wheel-zoom, drag-pan, scale clamp and bounded pixmap cache rather than a second
implementation of them.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QWidget

from insulation_coordination.rules.importer.extract import ImportedRuleDraft

# Regions are rendered at twice the scale they open at, so zooming in reads the print rather
# than an upscaled bitmap. A reviewer judging a cell has to read the page's small print.
# ponytail: fixed render resolution with a 2x headroom, not a re-render per zoom step; if a
# reviewer needs to go past MAX_PAGE_SCALE, re-render the region at the zoomed resolution.
PAGE_RESOLUTION = 220
INITIAL_PAGE_SCALE = 0.5
MIN_PAGE_SCALE = 0.1
MAX_PAGE_SCALE = 4.0
PAGE_GAP = 12.0
# ponytail: a 220 dpi page costs about 20 MB as a pixmap, so the cache is dropped wholesale
# rather than tracked by use order. Re-rendering one page costs a fraction of a second.
PAGE_CACHE_LIMIT = 8
#: Extra margin around a declared region, in PDF points. A crop flush to the reviewed bbox
#: clips ascenders and descenders and reads as a smudge; this is legibility only, and small
#: enough that no neighbouring line of unreviewed text is displayed as if it were evidence.
REGION_PADDING = 4.0

#: One region to render: a page number and, optionally, the bbox on it to crop to. ``None``
#: renders the whole page.
Region = tuple[int, tuple[float, float, float, float] | None]


def source_pdf_paths(
    draft: ImportedRuleDraft,
    paths: tuple[Path, ...],
) -> dict[str, Path]:
    """Map each recognized standard to the PDF on disk it was extracted from.

    Matching is by content digest, not filename, so a renamed or swapped file
    cannot end up displayed beside another standard's grid.
    """
    digests: dict[str, Path] = {}
    for path in paths:
        try:
            digests[hashlib.sha256(Path(path).read_bytes()).hexdigest()] = Path(path)
        except OSError:
            continue
    return {
        identity.standard: digests[identity.sha256]
        for identity in getattr(draft, "source_identities", ())
        if identity.sha256 in digests
    }


class _PageGraphicsView(QGraphicsView):
    """Zoomable, pannable read-only view of the source pages.

    Same scheme as the curve review's source view: the wheel scales the view, and the drag
    mode pans it. Anchored under the mouse so zooming keeps the print the cursor is on.
    """

    def __init__(self, scene: QGraphicsScene) -> None:
        super().__init__(scene)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform)

    def wheelEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        # Clamped, or a reviewer can scroll the page down to nothing and never find it again.
        if MIN_PAGE_SCALE <= self.transform().m11() * factor <= MAX_PAGE_SCALE:
            self.scale(factor, factor)


class PagePreview(_PageGraphicsView):
    """Stacked, zoomable rendering of the source regions one artifact was read from.

    Whole pages for a grid, cropped bboxes for a clause fragment's declared segments -- the
    caller says which. Passwords stay in memory for rendering only and are never stored.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        scene = QGraphicsScene()
        super().__init__(scene)
        # Owned by the view, so it is destroyed with it rather than outliving the dialog.
        scene.setParent(self)
        self._scene = scene
        if parent is not None:
            self.setParent(parent)
        self._cache: dict[tuple[Path, int, tuple[float, float, float, float] | None], QPixmap] = {}
        self._pixmaps: tuple[QPixmap, ...] = ()
        self._messages: tuple[str, ...] = ()
        self._passwords: dict[Path, str] = {}

    def set_passwords(self, passwords: dict[Path, str]) -> None:
        self._passwords = dict(passwords)

    @property
    def pixmaps(self) -> tuple[QPixmap, ...]:
        """The rendered regions currently in the pane, in reading order."""

        return self._pixmaps

    @property
    def messages(self) -> tuple[str, ...]:
        """Whatever the pane says in place of a region it could not show."""

        return self._messages

    def render_regions(
        self,
        path: Path | None,
        regions: tuple[Region, ...],
        *,
        unavailable: str,
    ) -> None:
        """Stack these regions in one zoomable scene, in reading order.

        Never raises: a region that cannot be rendered becomes a message in the pane, because a
        missing page must not take the review surface down with it.
        """

        self._scene.clear()
        pixmaps: list[QPixmap] = []
        messages: list[str] = []
        top = 0.0
        if path is None:
            messages.append(unavailable)
        else:
            for page_number, bbox in regions:
                try:
                    pixmap = self._pixmap(path, page_number, bbox)
                except (OSError, IndexError, TypeError, ValueError, PdfminerException) as error:
                    messages.append(f"Source page {page_number} could not be rendered: {error}")
                    continue
                item = self._scene.addPixmap(pixmap)
                item.setPos(0.0, top)
                top += pixmap.height() + PAGE_GAP
                pixmaps.append(pixmap)
        for message in messages:
            text = self._scene.addText(message)
            text.setPos(0.0, top)
            top += text.boundingRect().height() + PAGE_GAP
        self._pixmaps = tuple(pixmaps)
        self._messages = tuple(messages)
        self._scene.setSceneRect(self._scene.itemsBoundingRect())
        self.resetTransform()
        self.scale(INITIAL_PAGE_SCALE, INITIAL_PAGE_SCALE)

    def _pixmap(
        self,
        path: Path,
        page_number: int,
        bbox: tuple[float, float, float, float] | None,
    ) -> QPixmap:
        """Render one page or one padded region of it, raising nothing the caller cannot report."""

        key = (path, page_number, bbox)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        with pdfplumber.open(path, password=self._passwords.get(path, "")) as pdf:
            page = pdf.pages[page_number - 1]
            target = page if bbox is None else page.crop(_padded(bbox, page))
            image = target.to_image(resolution=PAGE_RESOLUTION)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
        pixmap = QPixmap()
        pixmap.loadFromData(buffer.getvalue())
        if len(self._cache) >= PAGE_CACHE_LIMIT:
            self._cache.clear()
        self._cache[key] = pixmap
        return pixmap


def _padded(
    bbox: tuple[float, float, float, float],
    page: pdfplumber.page.Page,
) -> tuple[float, float, float, float]:
    """The declared region with a legibility margin, clamped inside the page."""

    left, top, right, bottom = bbox
    return (
        max(float(page.bbox[0]), left - REGION_PADDING),
        max(float(page.bbox[1]), top - REGION_PADDING),
        min(float(page.bbox[2]), right + REGION_PADDING),
        min(float(page.bbox[3]), bottom + REGION_PADDING),
    )


__all__ = ["PagePreview", "Region", "source_pdf_paths"]
