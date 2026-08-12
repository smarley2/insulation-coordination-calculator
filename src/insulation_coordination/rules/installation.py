from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import platformdirs

from insulation_coordination.domain.rules import RulePackage
from insulation_coordination.rules.archive import load_rule_package, write_rule_package


@dataclass(frozen=True)
class InstalledRulePackage:
    path: Path
    package: RulePackage


def default_rules_dir() -> Path:
    return platformdirs.user_data_path("icc") / "rules"


def install_rule_package(source: Path, rules_dir: Path | None = None) -> InstalledRulePackage:
    package = load_rule_package(Path(source))
    destination_dir = Path(rules_dir) if rules_dir is not None else default_rules_dir()
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / (
        f"{package.manifest.package_id}-{package.manifest.version}.icrules"
    )
    write_rule_package(destination, package)
    return InstalledRulePackage(destination, load_rule_package(destination))
