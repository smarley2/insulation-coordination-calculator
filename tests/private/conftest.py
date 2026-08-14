"""Locate the maintainer's licensed PDFs by identifying them, never by filename."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from insulation_coordination.rules.importer.extract import (
    _REQUIRED_RECIPES,
    ImportedRuleDraft,
    extract_draft,
)
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


@pytest.fixture(scope="session")
def installed_grammars() -> dict[str, object]:
    """The maintainer's clause-fact grammars, or a clean skip when they are not installed.

    Amendment A1 moved every grammar mapping source phrasing to typed meaning beside the licensed
    material, so it is as absent from a public checkout as the PDFs are -- and a test asserting what
    a declared rule reads has to skip for the same reason, rather than fail because nothing was
    proposed. Identified by the recipe's own file name inside the licensed folder; the *content* is
    then validated by the grammar models themselves on the way in.
    """

    from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
        SUPPLY_FACT_GRAMMAR_FILE,
        supply_fact_proposal_grammars,
    )

    grammars = supply_fact_proposal_grammars()
    if not grammars:
        pytest.skip(f"no {SUPPLY_FACT_GRAMMAR_FILE} beside the licensed material")
    return dict(grammars)


@pytest.fixture(scope="session")
def supplied_paths(supplied_standards: dict[str, Path]) -> tuple[Path, ...]:
    """The licensed documents in the order extraction expects them."""

    return tuple(supplied_standards[recipe] for recipe in sorted(_REQUIRED_RECIPES))


@pytest.fixture(scope="session")
def extracted_draft(supplied_paths: tuple[Path, ...]) -> ImportedRuleDraft:
    """One import of all three licensed documents, shared by every test that reads it.

    Importing costs about twenty seconds, most of it rasterizing the source figures, and
    the private tests used to repeat it a dozen times. A draft is a frozen model and every
    review step returns a new one, so sharing this base draft cannot leak state between
    tests. A test that needs a second, independent import -- the determinism ones -- calls
    ``extract_draft`` itself, because extracting twice is the assertion there.
    """
    return extract_draft(supplied_paths)


@pytest.fixture(scope="session")
def reviewed_draft(extracted_draft: ImportedRuleDraft) -> ImportedRuleDraft:
    """One full review pass over the shared import, shared by every test that needs it.

    Reviewing resolves every extracted review item one at a time, which costs about as much
    as the import itself, and most tests want the state after review rather than the review
    process. A test that asserts the review process runs its own pass.

    The helper is imported here rather than at module scope because it lives beside the
    tests that assert the review lifecycle, and conftest is imported before them.
    """
    from tests.private.test_iec62477_dvc_tables import _review_all_c2_proposals

    return _review_all_c2_proposals(extracted_draft)
