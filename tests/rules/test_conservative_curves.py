"""Conservative reconstruction proof. Synthetic only."""

from __future__ import annotations

from decimal import Decimal

from insulation_coordination.rules.importer.curves import (
    ConservatismReport,
    conservative_simplify,
    prove_conservative,
)


def test_prove_conservative_rejects_candidate_above_envelope() -> None:
    """A candidate point above the lower uncertainty envelope fails the proof."""

    source = [(Decimal(x), Decimal(100)) for x in range(11)]
    tolerance = Decimal(2)
    candidate = [(Decimal(0), Decimal(99)), (Decimal(10), Decimal(103))]
    report = prove_conservative(source, candidate, tolerance)
    assert isinstance(report, ConservatismReport)
    assert report.proven is False
    assert report.maximum_positive_voltage_error > Decimal(0)


def test_prove_conservative_accepts_candidate_on_lower_boundary() -> None:
    source = [(Decimal(x), Decimal(100)) for x in range(11)]
    tolerance = Decimal(2)
    candidate = [(Decimal(0), Decimal(98)), (Decimal(10), Decimal(98))]
    report = prove_conservative(source, candidate, tolerance)
    assert report.proven is True
    assert report.maximum_positive_voltage_error <= Decimal(0)


def test_conservative_simplify_rounds_time_outward_voltage_downward() -> None:
    points = [
        (Decimal("1.004"), Decimal("100.4")),
        (Decimal("9.996"), Decimal("100.4")),
    ]
    simplified = conservative_simplify(points, Decimal(2))
    assert simplified[0][0] <= points[0][0]
    assert simplified[-1][0] >= points[-1][0]
    assert all(y <= Decimal("100.4") for _, y in simplified)


def test_simplify_never_rounds_time_inward_or_voltage_upward() -> None:
    points = [(Decimal("5.5"), Decimal("50.5")), (Decimal("6.5"), Decimal("60.5"))]
    simplified = conservative_simplify(points, Decimal(1))
    assert simplified[0][0] <= Decimal("5.5")
    assert simplified[-1][0] >= Decimal("6.5")
    assert simplified[0][1] <= Decimal("50.5")
    assert simplified[1][1] <= Decimal("60.5")
