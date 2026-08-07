"""Locate the maintainer's licensed PDFs by identifying them, never by filename."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from insulation_coordination.rules.importer.extract import _REQUIRED_RECIPES
from insulation_coordination.rules.importer.identify import (
    StandardIdentificationError,
    identify_standard,
)


@pytest.fixture(scope="session")
def supplied_standards() -> dict[str, Path]:
    repository = Path(__file__).parents[2]
    directory = Path(os.environ.get("ICC_PRIVATE_STANDARDS_DIR", repository / "standards"))
    if not directory.is_dir():
        pytest.skip(f"no licensed standards directory at {directory}")
    found: dict[str, list[Path]] = {}
    for candidate in sorted(directory.glob("*.pdf")):
        try:
            identity = identify_standard(candidate)
        except StandardIdentificationError:
            continue
        found.setdefault(identity.recipe_id, []).append(candidate)
    duplicated = sorted(recipe for recipe, paths in found.items() if len(paths) > 1)
    if duplicated:
        pytest.skip(f"more than one document identifies as {', '.join(duplicated)}")
    missing = sorted(_REQUIRED_RECIPES - set(found))
    if missing:
        pytest.skip(f"no licensed document found for {', '.join(missing)}")
    return {recipe: paths[0] for recipe, paths in found.items()}
