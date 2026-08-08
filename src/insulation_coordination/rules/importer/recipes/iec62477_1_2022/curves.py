"""IEC 62477-1:2022 curve recipes. Structural locators only.

Pages, figure numbers, axis kinds/units/scales, and the permitted variant/segment
vocabulary. No curve coordinates, labels, or source values live here.
"""

from __future__ import annotations

from typing import Literal

from insulation_coordination.domain.rules import FaultTimeVoltageSelector
from insulation_coordination.rules.importer.identify import CurveAuditSpec
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids

_SELECTOR_SUBJECTS: tuple[Literal["accessible_circuit", "conductive_accessible_part"], ...] = (
    "accessible_circuit",
    "conductive_accessible_part",
)
_SELECTOR_BASES: tuple[Literal["ac_rms", "ac_peak", "dc"], ...] = ("ac_rms", "ac_peak", "dc")


def _variant_slots() -> tuple[FaultTimeVoltageSelector, ...]:
    return tuple(
        FaultTimeVoltageSelector(
            subject=subject,
            voltage_basis=basis,
            dvc_context=None,
            environment_context=None,
        )
        for subject in _SELECTOR_SUBJECTS
        for basis in _SELECTOR_BASES
    )


def _spec(figure: str, page: int) -> CurveAuditSpec:
    return CurveAuditSpec(
        semantic_id=ids.DVC_FAULT_TIME_VOLTAGE,
        figure=figure,
        page_number=page,
        expected_bbox=(70.9, 120.0, 524.4, 700.0),
        expected_pixel_size=None,
        x_quantity_kind="duration",
        x_unit="s",
        y_quantity_kind="voltage",
        y_unit="V",
        x_scale="log10",
        y_scale="log10",
        variant_slots=_variant_slots(),
        permitted_segment_types=("continuous", "plateau"),
        permitted_interpolations=("log_log", "constant"),
    )


CURVES: tuple[CurveAuditSpec, ...] = (
    _spec("5", 54),
    _spec("6", 55),
    _spec("7", 56),
)

__all__ = ["CURVES"]
