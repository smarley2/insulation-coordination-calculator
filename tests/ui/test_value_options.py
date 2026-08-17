from __future__ import annotations

import ast
from pathlib import Path

from insulation_coordination.ui import value_options
from insulation_coordination.ui.value_options import impulse_options
from tests.fixtures.synthetic_rules import synthetic_rule_package
from tests.ui.conftest import SYNTHETIC_IMPULSE_V, with_synthetic_impulse_axis


def test_impulse_options_come_from_the_package_axis() -> None:
    package = with_synthetic_impulse_axis(synthetic_rule_package())

    options = impulse_options(package)

    assert tuple(value for _text, value in options) == SYNTHETIC_IMPULSE_V


def test_a_whole_level_stays_whole_in_volts() -> None:
    """A project stores what the combo offers, so 2.2 kV must save as 2200, not 2200.0."""
    package = with_synthetic_impulse_axis(synthetic_rule_package())

    options = impulse_options(package)

    assert [str(value) for _text, value in options] == ["110", "2200", "7700", "33000"]


def test_no_package_offers_no_levels() -> None:
    assert impulse_options(None) == ()


def test_an_unapproved_package_offers_no_levels() -> None:
    package = with_synthetic_impulse_axis(synthetic_rule_package())
    unapproved = package.model_copy(
        update={"manifest": package.manifest.model_copy(update={"approved": False})}
    )

    assert impulse_options(unapproved) == ()


def test_an_incompatible_package_offers_no_levels() -> None:
    package = with_synthetic_impulse_axis(synthetic_rule_package())
    incompatible = package.model_copy(
        update={"manifest": package.manifest.model_copy(update={"compatible": False})}
    )

    assert impulse_options(incompatible) == ()


def test_a_package_without_the_axis_offers_no_levels() -> None:
    """Nothing may stand in for an axis the active package does not carry."""
    assert impulse_options(synthetic_rule_package()) == ()


def test_no_option_series_survives_in_public_source() -> None:
    """The unavailable state is the only answer to a missing package.

    An embedded series would be a silent fallback: the field would keep offering
    levels this build has no approved rule for.
    """
    tree = ast.parse(Path(value_options.__file__ or "").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Tuple | ast.List | ast.Set | ast.Dict):
            continue
        numbers = [
            child
            for child in ast.walk(node)
            if isinstance(child, ast.Constant) and isinstance(child.value, int | float)
        ]
        assert len(numbers) < 3, f"value_options.py:{node.lineno} holds a numeric series"
