"""IEC 62477-1:2022 curve recipes. Structural locators only.

Pages, figure numbers, axis kinds/units/scales, and the permitted variant/segment
vocabulary. No curve coordinates, labels, or source values live here.
"""

from __future__ import annotations

from insulation_coordination.domain.rules import FaultTimeVoltageSelector
from insulation_coordination.rules.importer.identify import CurveAuditSpec
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids

_SELECTORS = {
    "5": (
        FaultTimeVoltageSelector(
            subject="accessible_circuit",
            voltage_basis="dc",
            dvc_context="b",
            environment_context="dry",
        ),
        FaultTimeVoltageSelector(
            subject="accessible_circuit",
            voltage_basis="dc",
            dvc_context="as",
            environment_context="dry",
        ),
        FaultTimeVoltageSelector(
            subject="accessible_circuit",
            voltage_basis="dc",
            dvc_context="as",
            environment_context="wet_and_saltwater_wet",
        ),
    ),
    "6": (
        FaultTimeVoltageSelector(
            subject="accessible_circuit",
            voltage_basis="ac_peak",
            dvc_context="b",
            environment_context="dry",
        ),
        FaultTimeVoltageSelector(
            subject="accessible_circuit",
            voltage_basis="ac_peak",
            dvc_context="as",
            environment_context="dry",
        ),
        FaultTimeVoltageSelector(
            subject="accessible_circuit",
            voltage_basis="ac_peak",
            dvc_context="as",
            environment_context="wet_and_saltwater_wet",
        ),
    ),
    "7": (
        FaultTimeVoltageSelector(
            subject="conductive_accessible_part",
            voltage_basis="dc",
            dvc_context=None,
            environment_context=None,
        ),
        FaultTimeVoltageSelector(
            subject="conductive_accessible_part",
            voltage_basis="ac_peak",
            dvc_context=None,
            environment_context=None,
        ),
    ),
}


def _spec(figure: str, page: int) -> CurveAuditSpec:
    return CurveAuditSpec(
        semantic_id=ids.DVC_FAULT_TIME_VOLTAGE,
        figure=figure,
        page_number=page,
        expected_bbox=(70.9, 120.0, 524.4, 700.0),
        expected_pixel_size=None,
        x_quantity_kind="duration",
        x_unit="s",
        x_source_unit="ms",
        y_quantity_kind="voltage",
        y_unit="V",
        x_scale="log10",
        y_scale="log10",
        variant_slots=_SELECTORS[figure],
        permitted_segment_types=("continuous", "plateau"),
        permitted_interpolations=("log_log", "constant"),
    )


CURVES: tuple[CurveAuditSpec, ...] = (
    _spec("5", 54),
    _spec("6", 55),
    _spec("7", 56),
)

__all__ = ["CURVES"]
