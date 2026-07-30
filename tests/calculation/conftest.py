import sys
from pathlib import Path

import pytest

from insulation_coordination.domain.rules import RulePackage

sys.path.insert(0, str(Path(__file__).parents[2]))

from tests.fixtures.synthetic_rules import synthetic_part1_rule_package


@pytest.fixture
def synthetic_rules() -> RulePackage:
    return synthetic_part1_rule_package()
