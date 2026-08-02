"""Render the reviewed SVG into the native icon formats used by each package."""

from __future__ import annotations

import argparse
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def render_icons(source: Path, destination: Path) -> tuple[Path, ...]:
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    image = QImage(512, 512, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        painter.end()
        raise ValueError(f"invalid SVG icon: {source}")
    renderer.render(painter)
    painter.end()
    outputs = tuple(destination / f"icc{suffix}" for suffix in (".png", ".ico", ".icns"))
    for output in outputs:
        if not image.save(str(output)):
            raise OSError(f"could not write icon: {output}")
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    render_icons(args.source, args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
