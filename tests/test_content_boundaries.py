"""Regression tests for the public/private content boundary.

Each test asserts a boundary property that already holds: the private suite
skips cleanly when the licensed documents are absent, no private artifact type
is tracked in the public tree, no inline factor is left in the tracked tree, and
a synthetic fixture package does not claim an IEC standard as its source
identity. Boundary properties that are not yet true (rule-backed UI options) are
inventoried in docs/licensed-content-audit.md instead of being asserted here.

The inline-factor property became true with issue #40's Task 4: both findings
were reinforced treatment factors, and both are now resolved from the approved
package.

Four fixture packages are deliberately outside the identity property and so are
not listed below. The DVC package has to carry the identity the guidance service
gates on, the supply package has to carry the identity ``read_supply_rules``
gates on, and the verification package and the verification topology module's
dielectric package both have to carry the identity ``read_verification_rules``
gates on, because in every case that gate is the behavior under test - including
its refusal of the wrong edition, which needs a package that is right about
everything else. Their numbers, steps and conditions are invented and their
document ids and notes say so. All four are inventoried in
docs/licensed-content-audit.md.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from insulation_coordination.domain.rules import RulePackage
from scripts.scan_licensed_content import (
    PRIVATE_NAMES,
    PRIVATE_SUFFIXES,
    iter_files,
    scan_tree,
)
from tests.fixtures.synthetic_rules import (
    claimed_standards,
    synthetic_hf_rule_package,
    synthetic_part1_rule_package,
    synthetic_rule_package,
)

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


def test_no_inline_factor_is_left_in_the_tracked_tree() -> None:
    offending = [
        f"{finding.path.as_posix()}:{finding.line}"
        for finding in scan_tree(REPOSITORY)
        if finding.category == "inline-factor"
    ]

    assert offending == []


@pytest.mark.parametrize(
    "factory",
    (synthetic_rule_package, synthetic_part1_rule_package, synthetic_hf_rule_package),
    ids=("base", "part1", "high-frequency"),
)
def test_synthetic_fixtures_do_not_claim_iec_identity(
    factory: Callable[[], RulePackage],
) -> None:
    standards = claimed_standards(factory())

    assert standards
    assert not any(standard.upper().startswith("IEC") for standard in standards)
