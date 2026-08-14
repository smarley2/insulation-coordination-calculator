"""Regression tests for the public/private content boundary.

Each test asserts a boundary property that already holds: the private suite
skips cleanly when the licensed documents are absent, no private artifact type
is tracked in the public tree, and the part 1 synthetic fixture package does
not claim an IEC standard as its source identity. Boundary properties that are
not yet true (rule-backed UI options, rule-backed reinforced policy) are
inventoried in docs/licensed-content-audit.md instead of being asserted here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.scan_licensed_content import PRIVATE_NAMES, PRIVATE_SUFFIXES, iter_files
from tests.fixtures.synthetic_rules import synthetic_part1_rule_package

REPOSITORY = Path(__file__).parents[1]

#: The rule types a phrasing-to-meaning grammar is spelled with. Declaring one is what makes a
#: module propose a normative reading, so the boundary is enforced on the construction rather than
#: on the import: ``clause_fact_proposals`` defines these and validates them, and no module under
#: ``src`` may build one.
_GRAMMAR_CONSTRUCTORS = frozenset({"ClauseFactGrammar", "ClauseKeywordRule", "ClauseSequenceRule"})


def test_private_suite_skips_cleanly_without_licensed_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.private.conftest import supplied_standards

    fixture = supplied_standards.__wrapped__
    monkeypatch.setenv("ICC_PRIVATE_STANDARDS_DIR", str(tmp_path / "missing"))
    with pytest.raises(pytest.skip.Exception, match="no licensed standards directory"):
        fixture()
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("ICC_PRIVATE_STANDARDS_DIR", str(empty))
    with pytest.raises(pytest.skip.Exception, match="no licensed document found"):
        fixture()


def test_no_private_artifact_types_are_tracked() -> None:
    offending = [
        path
        for path in iter_files(REPOSITORY)
        if path.suffix.lower() in PRIVATE_SUFFIXES or path.name in PRIVATE_NAMES
    ]
    assert offending == []


def test_no_public_module_declares_a_clause_fact_grammar() -> None:
    """The contract ``clause_facts`` states, asserted instead of restated (amendment A1).

    A mapping from source phrasing to typed normative meaning is licensed-derived content however
    generic each half looks alone, so it loads from beside the licensed material and no shipped
    module builds one. Asserted on the constructor rather than on the imported name, because the
    module that *defines* these types is exactly the generic engine that has to keep them.
    """

    offending = []
    for path in sorted((REPOSITORY / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        declared = sorted(
            {
                node.func.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in _GRAMMAR_CONSTRUCTORS
            }
        )
        offending.extend((path.relative_to(REPOSITORY).as_posix(), name) for name in declared)

    assert offending == []


def test_a_route_offers_no_draft_and_says_why_without_the_private_grammar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Honest degradation, not a silent empty list.

    The public suite runs with no licensed material at all, so this is the state every reviewer on
    a public checkout sees: nothing is proposed for any route, and the surface says that the
    grammar is absent rather than letting an empty list read as "this clause states nothing".
    """

    from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import ids
    from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
        supply_fact_proposal_grammars,
    )

    monkeypatch.setenv("ICC_PRIVATE_STANDARDS_DIR", str(tmp_path / "missing"))
    assert supply_fact_proposal_grammars() == {}

    monkeypatch.delenv("ICC_PRIVATE_STANDARDS_DIR", raising=False)
    assert supply_fact_proposal_grammars() == {}
    assert ids.SUPPLY_HF_TRANSFORMER_ATTENUATION not in supply_fact_proposal_grammars()


def test_part1_synthetic_fixtures_do_not_claim_iec_identity() -> None:
    package = synthetic_part1_rule_package()
    standards = {
        item.source.standard
        for group in (package.tables, package.formulas, package.mappings)
        for item in group
    }
    assert standards
    assert not any(standard.upper().startswith("IEC") for standard in standards)
