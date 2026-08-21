"""Locate the maintainer's licensed PDFs by identifying them, never by filename."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.rules.importer.extract import (
    _REQUIRED_RECIPES,
    ImportedRuleDraft,
    extract_draft,
)
from insulation_coordination.rules.importer.identify import (
    StandardIdentificationError,
    identify_standard,
)

#: The most workers this directory can be shared between and still report the truth.
#:
#: Its fixtures extract all three licensed PDFs and drive a full review-and-approve pass, and
#: they are session-scoped, so under xdist *every* worker builds its own copy. Past a few
#: workers they contend until the suite reports a different handful of fabricated failures each
#: run -- some as bare timeouts with no assertion, some as workers dying with "node down: Not
#: properly terminated". Measured on main: 104 passed, 1 skipped at -n 4, and at -n 12 one
#: passing run followed by two runs of six and seven failures with an xdist INTERNALERROR.
#:
#: That nondeterminism is the danger, not the failure: it has been read as a code regression
#: twice, and once as evidence the repository's --timeout=120 was too low, which measurement
#: later disproved. Raising the timeout does not help and neither does pinning the directory to
#: one worker with --dist loadgroup, which was tried here and did not hold.
_MAX_PRIVATE_WORKERS = 4


def pytest_cmdline_main(config: pytest.Config) -> None:
    """Refuse a worker count this directory cannot report the truth at.

    In the controller, before any worker exists: pytest loads this conftest up front when the
    command line names this directory, and refusing here is what makes the message readable.
    Raising it from inside a worker instead -- the obvious place, since that is where the
    contention is -- surfaces as an xdist INTERNALERROR whose assertion never mentions the cause.

    Silent when the command line does not name this directory: a whole-tree run collects it in
    the workers, where this hook has already been passed, so there is nothing to catch. CI is
    that case and is unaffected in any event, having no licensed PDFs to run these tests against.
    """

    workers = getattr(config.option, "numprocesses", None)
    if not isinstance(workers, int) or workers <= _MAX_PRIVATE_WORKERS:
        return
    raise pytest.UsageError(
        f"tests/private cannot report the truth at -n {workers}. Each worker extracts all three "
        f"licensed PDFs into its own session fixtures, and past {_MAX_PRIVATE_WORKERS} they "
        "contend until the suite invents a different handful of failures every run. Use "
        "`uv run pytest tests/private -n 4` -- the baseline there is 104 passed, 1 skipped -- or "
        "drop -n entirely to run serially. See issue #146."
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip this directory in a worker the whole-tree run gave too many siblings.

    The other half of the refusal above, for the case it cannot reach: ``pytest -n 12`` over the
    whole tree never names this directory on the command line, so the controller loads this
    conftest only inside the workers, by which time ``pytest_cmdline_main`` has long passed.
    A skip is the strongest thing a worker can say without an INTERNALERROR, and it is enough --
    the reviewer reads that this directory did not run and why, instead of reading a failure the
    contention invented.
    """

    workers = getattr(config, "workerinput", {}).get("workercount", 1)
    if workers <= _MAX_PRIVATE_WORKERS:
        return
    skip = pytest.mark.skip(
        reason=(
            f"not run: -n {workers} is too many workers for this directory to report the truth "
            "at. Run `uv run pytest tests/private -n 4` on its own. See issue #146."
        )
    )
    # This hook is handed the whole session's items, not this directory's -- a conftest is
    # loaded once and then speaks for every test collected. Filtering is what keeps the skip
    # from swallowing the public suite, which it did on the first attempt: 2 997 skipped.
    directory = Path(__file__).parent
    for item in items:
        if directory in Path(str(item.fspath)).parents:
            item.add_marker(skip)


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


@pytest.fixture(scope="session")
def approved_package(reviewed_draft: ImportedRuleDraft) -> RulePackage:
    """One approval of the shared review pass, shared by every test that reads the result.

    Approving projects every reviewed proposal into a rule and hashes the whole package, which
    costs about fifteen seconds, and the private tests used to repeat it once per test. A
    package is a frozen model and nothing a consumer does to one returns a changed package, so
    sharing this one cannot leak state between tests. A test whose assertion *is* the approval
    -- the manual-curve-review lifecycle, the ones that prove an unresolved draft is refused --
    calls ``approve_draft`` itself.

    The helper is imported here rather than at module scope because it lives beside the tests
    that assert the Slice C lifecycle, and conftest is imported before them.
    """

    from tests.private.test_iec62477_slice_c_roundtrip import _approved_slice_c

    return _approved_slice_c(reviewed_draft)


@pytest.fixture(scope="session")
def licensed_package(
    approved_package: RulePackage,
    tmp_path_factory: pytest.TempPathFactory,
) -> RulePackage:
    """The approved package as a consumer receives it: through the archive and back.

    Most tests want the package *after* the archive rather than the writing of it, so the round
    trip is shared too. A test whose assertion is the round trip -- one comparing the reloaded
    package against the one written -- writes its own archive.
    """

    archive = tmp_path_factory.mktemp("licensed-package") / "licensed.icrules"
    write_rule_package(archive, approved_package)
    return load_rule_package(archive)
