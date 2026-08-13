"""Regression tests for the public/private content boundary.

Each test asserts a boundary property that already holds: the private suite
skips cleanly when the licensed documents are absent, no private artifact type
is tracked in the public tree, and the part 1 synthetic fixture package does
not claim an IEC standard as its source identity. Boundary properties that are
not yet true (rule-backed UI options, rule-backed reinforced policy) are
inventoried in docs/licensed-content-audit.md instead of being asserted here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.scan_licensed_content import PRIVATE_NAMES, PRIVATE_SUFFIXES, iter_files
from tests.fixtures.synthetic_rules import synthetic_part1_rule_package

REPOSITORY = Path(__file__).parents[1]


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


def test_part1_synthetic_fixtures_do_not_claim_iec_identity() -> None:
    package = synthetic_part1_rule_package()
    standards = {
        item.source.standard
        for group in (package.tables, package.formulas, package.mappings)
        for item in group
    }
    assert standards
    assert not any(standard.upper().startswith("IEC") for standard in standards)
