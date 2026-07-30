import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from tests.fixtures.synthetic_rules import package_dict, synthetic_package  # noqa: F401
