from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from insulation_coordination.domain.enums import (
    ConstructionType,
    FieldCondition,
)
from insulation_coordination.domain.project import (
    NetClass,
    Project,
    ProjectDefaults,
    ProjectMetadata,
    RulePackageReference,
)
from insulation_coordination.project.pairs import reconcile_pairs


def _make_project() -> Project:
    nets = tuple(NetClass(id=UUID(int=i + 1), name=n) for i, n in enumerate(("HV+", "HV-")))
    return Project(
        id=UUID(int=100),
        metadata=ProjectMetadata(title="Editor Fields"),
        application_version="0.1.0",
        required_rules=RulePackageReference(
            package_id="iec-60664", version="2020.1", sha256="a" * 64
        ),
        defaults=ProjectDefaults(),
        net_classes=nets,
        pairs=reconcile_pairs(nets, ()),
    )


@pytest.fixture
def editor(qtbot):
    from insulation_coordination.ui.pair_editor import PairEditor

    project = _make_project()
    editor = PairEditor()
    editor.load_pair(project.pairs[0])
    qtbot.addWidget(editor)
    return editor


def test_set_impulse_override(editor) -> None:
    editor.set_impulse_override("800 V")
    assert editor.pair is not None
    assert editor.pair.impulse_v.is_override is True
    assert editor.pair.impulse_v.value == Decimal(800)
    assert editor._impulse_source_label.text() == "Override"


def test_clear_impulse_override(editor) -> None:
    editor.set_impulse_override("800 V")
    editor.clear_impulse_override()
    assert editor.pair is not None
    assert editor.pair.impulse_v.is_override is False
    assert editor._impulse_source_label.text() == "Default"


def test_set_field_override(editor) -> None:
    editor.set_field_override(FieldCondition.HOMOGENEOUS)
    assert editor.pair is not None
    assert editor.pair.field_condition.is_override
    assert editor.pair.field_condition.value == FieldCondition.HOMOGENEOUS
    assert editor._field_source_label.text() == "Override"


def test_set_radius_altitude_pollution_cti(editor) -> None:
    editor.set_radius_override("2.5")
    editor.set_altitude_override("1500")
    editor.set_pollution_override("3")
    editor.set_cti_override("II")
    assert editor.pair is not None
    assert editor.pair.electrode_radius_mm.value == Decimal("2.5")
    assert editor.pair.altitude_m.value == Decimal(1500)
    assert editor.pair.pollution_degree.value == 3
    assert editor.pair.cti_or_material_group.value == "II"
    assert editor._radius_source_label.text() == "Override"
    assert editor._altitude_source_label.text() == "Override"
    assert editor._pollution_source_label.text() == "Override"
    assert editor._cti_source_label.text() == "Override"


def test_set_construction_override_and_notes(editor) -> None:
    editor.set_construction_override(ConstructionType.PRINTED_WIRING)
    editor.set_notes("PVC insulation")
    assert editor.pair is not None
    assert editor.pair.construction_type.value == ConstructionType.PRINTED_WIRING
    assert editor.pair.notes == "PVC insulation"
    assert editor._construction_source_label.text() == "Override"


def test_rms_not_applicable_button(editor) -> None:
    editor._on_rms_na()
    assert editor.pair is not None
    assert editor.pair.voltages.long_term_rms_v.applicability == "not_applicable"
    assert editor.pair.voltages.long_term_rms_v.justification


def test_steady_not_applicable_button(editor) -> None:
    editor._on_steady_na()
    assert editor.pair is not None
    assert editor.pair.voltages.steady_state_peak_v.applicability == "not_applicable"
    assert editor.pair.voltages.steady_state_peak_v.justification


def test_temporary_not_applicable_button(editor) -> None:
    editor._on_to_na()
    assert editor.pair is not None
    assert editor.pair.voltages.temporary_overvoltage_peak_v.applicability == "not_applicable"
