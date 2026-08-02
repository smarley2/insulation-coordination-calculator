from pathlib import Path

import pytest

from insulation_coordination.domain.rules import RulePackageError
from insulation_coordination.rules.archive import load_rule_package, write_rule_package
from insulation_coordination.rules.installation import install_rule_package
from tests.fixtures.synthetic_rules import synthetic_rule_package


def test_install_rule_package_validates_and_reloads_canonical_archive(tmp_path: Path) -> None:
    source = tmp_path / "source.icrules"
    write_rule_package(source, synthetic_rule_package())

    installed = install_rule_package(source, tmp_path / "installed")

    assert installed.path.parent == tmp_path / "installed"
    assert installed.path.name == (
        f"{installed.package.manifest.package_id}-{installed.package.manifest.version}.icrules"
    )
    assert load_rule_package(installed.path).package_sha256 == installed.package.package_sha256


def test_install_rule_package_never_replaces_valid_install_with_bad_input(tmp_path: Path) -> None:
    source = tmp_path / "source.icrules"
    write_rule_package(source, synthetic_rule_package())
    installed = install_rule_package(source, tmp_path / "installed")
    before = installed.path.read_bytes()
    source.write_bytes(b"not a rule archive")

    with pytest.raises(RulePackageError):
        install_rule_package(source, tmp_path / "installed")

    assert installed.path.read_bytes() == before
