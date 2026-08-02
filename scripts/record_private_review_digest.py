"""Record a human-reviewed digest without printing licensed source values."""

from __future__ import annotations

import argparse
from pathlib import Path

from insulation_coordination.rules.importer.extract import extract_draft
from insulation_coordination.rules.importer.identify import identify_standard
from insulation_coordination.rules.importer.review import draft_review_digest

CONFIRMATION = "I reviewed these extracted sources"


def record_private_review_digest(paths: tuple[Path, Path], destination: Path) -> str:
    draft = extract_draft(paths)
    digest = draft_review_digest(draft)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(digest + "\n", encoding="ascii")
    temporary.replace(destination)
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", nargs=2, type=Path, metavar="PDF")
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    identities = tuple(identify_standard(path) for path in args.pdf)
    draft = extract_draft(tuple(args.pdf))
    digest = draft_review_digest(draft)
    print("Identified standards:", ", ".join(f"{item.standard} {item.edition}" for item in identities))
    print("Raw-grid dimensions:", ", ".join(f"{grid.id}={grid.rows}x{grid.columns}" for grid in draft.raw_grids))
    print("Review-item count:", len(draft.review_items))
    print("Digest:", digest)
    if input(f'Type "{CONFIRMATION}" to write the digest: ') != CONFIRMATION:
        raise SystemExit("digest not recorded")
    record_private_review_digest(tuple(args.pdf), args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
