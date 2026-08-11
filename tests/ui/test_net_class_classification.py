"""The net-classification panel: five closed choices, one edit at a time.

Covers the widget itself (``NetClassClassificationPanel``) and the guidance registry
behind its help controls (``topology_guidance``), since the brief for this task folds
both into one focused test file.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QPushButton

from insulation_coordination.domain.enums import (
    CircuitSourceRelationship,
    ConnectionExposure,
    DecisiveVoltageClass,
    NetClassType,
    ReviewState,
)
from insulation_coordination.domain.project import NetClass
from insulation_coordination.domain.topology import GalvanicDomain
from insulation_coordination.ui.help_indicator import HelpIndicator
from insulation_coordination.ui.net_class_classification import NetClassClassificationPanel
from insulation_coordination.ui.topology_guidance import (
    TopologyGuidanceId,
    guidance_id_for_dvc,
)
from insulation_coordination.ui.voltage_guidance import (
    MAX_SHORT_TEXT_LENGTH,
    guidance_for,
    register_guidance,
)


def _circuit(**overrides: object) -> NetClass:
    defaults: dict[str, object] = {"id": uuid4(), "name": "HV"}
    defaults.update(overrides)
    return NetClass(**defaults)


def _non_circuit(net_type: NetClassType = NetClassType.PE_BONDED_CONDUCTIVE_PART) -> NetClass:
    return NetClass(
        id=uuid4(),
        name="Chassis",
        net_type=net_type,
        source_relationship=None,
        connection_exposure=None,
        decisive_voltage_class=None,
        galvanic_domain_id=None,
    )


@pytest.fixture
def panel(qtbot) -> NetClassClassificationPanel:
    widget = NetClassClassificationPanel()
    qtbot.addWidget(widget)
    return widget


# --- topology_guidance registry -------------------------------------------------


def test_every_topology_id_has_guidance() -> None:
    for guidance_id in TopologyGuidanceId:
        guidance = guidance_for(guidance_id)
        assert guidance.id is guidance_id
        assert guidance.title.strip()
        assert guidance.short_text.strip()
        assert guidance.detailed_text.strip()


def test_topology_short_text_fits_a_tooltip() -> None:
    for guidance_id in TopologyGuidanceId:
        assert len(guidance_for(guidance_id).short_text) <= MAX_SHORT_TEXT_LENGTH


def test_registering_a_duplicate_id_is_rejected() -> None:
    from insulation_coordination.ui.voltage_guidance import VoltageGuidance, VoltageGuidanceId

    duplicate = VoltageGuidance(
        id=VoltageGuidanceId.FREQUENCY,
        title="x",
        short_text="x",
        detailed_text="x",
    )
    with pytest.raises(ValueError, match="already registered"):
        register_guidance(duplicate)


def test_dvc_guidance_covers_exactly_the_four_iec_classes() -> None:
    ids = {guidance_id_for_dvc(value) for value in DecisiveVoltageClass}
    assert len(ids) == 4


def test_obc_guidance_examples_carry_the_applicability_warning_verbatim() -> None:
    """The applicability warning travels with the OBC example wherever it is shown.

    Shown as guide content, the example carries the one constant verbatim, never a
    paraphrase that could drift from it.
    """
    from insulation_coordination.domain.display import OBC_APPLICABILITY_WARNING

    guidance_ids_with_obc_examples = (
        TopologyGuidanceId.GALVANIC_DOMAIN_ASSIGNMENT,
        TopologyGuidanceId.BARRIER_VERIFIED_GALVANIC_ISOLATION,
        TopologyGuidanceId.BARRIER_NO_GALVANIC_ISOLATION,
    )
    for guidance_id in guidance_ids_with_obc_examples:
        obc_examples = [
            example for example in guidance_for(guidance_id).examples if "OBC" in example
        ]
        assert obc_examples, f"{guidance_id} has no OBC example"
        assert all(OBC_APPLICABILITY_WARNING in example for example in obc_examples)


def test_topology_guidance_module_does_not_touch_widgets() -> None:
    import inspect

    from insulation_coordination.ui import topology_guidance

    assert "PySide6" not in inspect.getsource(topology_guidance)


# --- widget: structure -----------------------------------------------------------


def test_dropdowns_appear_in_the_required_order(panel: NetClassClassificationPanel) -> None:
    combos = panel.findChildren(QComboBox)
    assert combos == [
        panel._type_combo,
        panel._source_combo,
        panel._exposure_combo,
        panel._dvc_combo,
        panel._domain_combo,
    ]


def test_every_dropdown_carries_a_help_indicator(panel: NetClassClassificationPanel) -> None:
    for help_indicator in (
        panel._type_help,
        panel._source_help,
        panel._exposure_help,
        panel._dvc_help,
        panel._domain_help,
    ):
        assert isinstance(help_indicator, HelpIndicator)


def test_panel_has_a_how_to_choose_button(panel: NetClassClassificationPanel) -> None:
    assert isinstance(panel._how_to_choose, QPushButton)
    assert panel._how_to_choose.text() == "How to choose"


def test_how_to_choose_opens_the_overview_guidance(
    panel: NetClassClassificationPanel, qtbot
) -> None:
    dialog = None

    def capture() -> None:
        nonlocal dialog
        from insulation_coordination.ui.help_indicator import GuidanceDialog

        dialog = panel.findChild(GuidanceDialog)

    panel._how_to_choose.clicked.connect(capture)
    qtbot.mouseClick(panel._how_to_choose, Qt.MouseButton.LeftButton)
    assert dialog is not None
    qtbot.addWidget(dialog)
    assert dialog.isVisible()
    assert (
        guidance_for(TopologyGuidanceId.CLASSIFICATION_OVERVIEW).detailed_text[:30]
        in dialog.body_text()
    )


def test_panel_has_a_dvc_guide_button(panel: NetClassClassificationPanel) -> None:
    assert isinstance(panel._dvc_guide_button, QPushButton)
    assert panel._dvc_guide_button.text() == "DVC guide"


def test_dvc_guide_button_disabled_for_a_non_circuit_net(
    panel: NetClassClassificationPanel,
) -> None:
    panel.set_net_class(_non_circuit())
    assert not panel._dvc_guide_button.isEnabled()


def test_dvc_guide_button_disabled_when_nothing_selected(
    panel: NetClassClassificationPanel,
) -> None:
    panel.set_net_class(_circuit())
    panel.set_net_class(None)
    assert not panel._dvc_guide_button.isEnabled()


def test_dvc_guide_reads_the_project_s_active_rules_package(
    panel: NetClassClassificationPanel, qtbot
) -> None:
    from tests.fixtures.synthetic_rules import synthetic_dvc_rule_package

    package = synthetic_dvc_rule_package()
    panel.set_rules_package(package)
    panel.set_net_class(_circuit(decisive_voltage_class=DecisiveVoltageClass.DVC_AS))

    from insulation_coordination.ui.dvc_guide import DvcGuideDialog

    dialog: DvcGuideDialog | None = None

    def capture() -> None:
        nonlocal dialog
        dialog = panel.findChild(DvcGuideDialog)

    panel._dvc_guide_button.clicked.connect(capture)
    qtbot.mouseClick(panel._dvc_guide_button, Qt.MouseButton.LeftButton)
    assert dialog is not None
    qtbot.addWidget(dialog)
    assert dialog.isVisible()
    from insulation_coordination.domain.dvc import VOLTAGE_QUANTITY_COLUMN_TOKENS

    rms_label = dict(VOLTAGE_QUANTITY_COLUMN_TOKENS)["voltage-quantity-1"]
    assert f"{rms_label}: 11 V" in dialog.body_text()


def test_every_classification_help_control_can_cite_the_active_package(
    panel: NetClassClassificationPanel, qtbot
) -> None:
    """Each ⓘ resolves the rules its guidance names against the project's own package."""
    from tests.fixtures.synthetic_rules import synthetic_dvc_rule_package

    panel.set_rules_package(synthetic_dvc_rule_package())
    panel.set_net_class(_circuit(decisive_voltage_class=DecisiveVoltageClass.DVC_AS))

    dialog = panel._dvc_help.open_details()
    qtbot.addWidget(dialog)
    assert "iec62477_2022.dvc.voltage_limits: IEC 62477-1 2022" in dialog.body_text()

    for indicator in (
        panel._type_help,
        panel._source_help,
        panel._exposure_help,
        panel._domain_help,
    ):
        assert indicator._package is not None


def test_dvc_guide_degrades_gracefully_with_no_rules_package_loaded(
    panel: NetClassClassificationPanel, qtbot
) -> None:
    panel.set_net_class(_circuit(decisive_voltage_class=DecisiveVoltageClass.DVC_B))

    from insulation_coordination.ui.dvc_guide import DvcGuideDialog

    dialog: DvcGuideDialog | None = None

    def capture() -> None:
        nonlocal dialog
        dialog = panel.findChild(DvcGuideDialog)

    panel._dvc_guide_button.clicked.connect(capture)
    qtbot.mouseClick(panel._dvc_guide_button, Qt.MouseButton.LeftButton)
    assert dialog is not None
    qtbot.addWidget(dialog)
    assert "No rule package is loaded" in dialog.body_text()


# --- widget: enabled / disabled / N/A state --------------------------------------


def test_circuit_net_enables_every_field(panel: NetClassClassificationPanel) -> None:
    panel.set_net_class(_circuit())
    for combo in (
        panel._source_combo,
        panel._exposure_combo,
        panel._dvc_combo,
        panel._domain_combo,
    ):
        assert combo.isEnabled()
    assert panel._type_combo.isEnabled()


@pytest.mark.parametrize(
    "net_type",
    [
        NetClassType.PE_BONDED_CONDUCTIVE_PART,
        NetClassType.ACCESSIBLE_CONDUCTIVE_PART,
        NetClassType.ACCESSIBLE_INSULATING_SURFACE,
    ],
)
def test_non_circuit_net_disables_circuit_fields_and_shows_na(
    panel: NetClassClassificationPanel, net_type: NetClassType
) -> None:
    panel.set_net_class(_non_circuit(net_type))
    for combo in (
        panel._source_combo,
        panel._exposure_combo,
        panel._dvc_combo,
        panel._domain_combo,
    ):
        assert not combo.isEnabled()
        assert combo.count() == 1
        assert combo.currentText() == "N/A"
        assert combo.itemData(0) is None
    # The net class type itself always stays answerable - it is what decides everything else.
    assert panel._type_combo.isEnabled()


def test_no_net_selected_disables_every_field(panel: NetClassClassificationPanel) -> None:
    panel.set_net_class(_circuit())
    panel.set_net_class(None)
    for combo in (
        panel._type_combo,
        panel._source_combo,
        panel._exposure_combo,
        panel._dvc_combo,
        panel._domain_combo,
    ):
        assert not combo.isEnabled()


def test_dvc_dropdown_offers_exactly_four_entries(panel: NetClassClassificationPanel) -> None:
    panel.set_net_class(_circuit())
    assert panel._dvc_combo.count() == 4
    assert [panel._dvc_combo.itemText(i) for i in range(4)] == [
        "Not evaluated",
        "DVC A-s",
        "DVC B",
        "DVC C",
    ]


def test_domain_dropdown_offers_only_unset_with_no_project_domains(
    panel: NetClassClassificationPanel,
) -> None:
    panel.set_net_class(_circuit())
    assert panel._domain_combo.count() == 1
    assert panel._domain_combo.itemText(0) == "Unset"
    assert panel._domain_combo.itemData(0) is None


def test_domain_dropdown_lists_project_domains(panel: NetClassClassificationPanel) -> None:
    domain = GalvanicDomain(id=uuid4(), name="Primary side", is_direct_source_domain=True)
    panel.set_net_class(_circuit(), (domain,))
    assert panel._domain_combo.count() == 2
    assert panel._domain_combo.itemText(1) == "Primary side"
    assert panel._domain_combo.itemData(1) == domain.id


# --- widget: editing --------------------------------------------------------------


def test_changing_the_source_relationship_emits_one_update(
    panel: NetClassClassificationPanel, qtbot
) -> None:
    net = _circuit()
    panel.set_net_class(net)
    with qtbot.waitSignal(panel.net_class_changed, timeout=1000) as blocker:
        index = panel._source_combo.findData(CircuitSourceRelationship.MAINS_CONNECTED)
        panel._source_combo.setCurrentIndex(index)
    (updated,) = blocker.args
    assert updated.source_relationship is CircuitSourceRelationship.MAINS_CONNECTED
    assert updated.classification_review_state is ReviewState.USER_CONFIRMED
    # Every other field is untouched by this one edit.
    assert updated.connection_exposure == net.connection_exposure
    assert updated.decisive_voltage_class == net.decisive_voltage_class
    assert updated.galvanic_domain_id == net.galvanic_domain_id
    assert updated.name == net.name
    assert updated.id == net.id


def test_changing_the_connection_exposure_emits_one_update(
    panel: NetClassClassificationPanel, qtbot
) -> None:
    panel.set_net_class(_circuit())
    with qtbot.waitSignal(panel.net_class_changed, timeout=1000) as blocker:
        index = panel._exposure_combo.findData(ConnectionExposure.LONG_OUTDOOR_LINE)
        panel._exposure_combo.setCurrentIndex(index)
    (updated,) = blocker.args
    assert updated.connection_exposure is ConnectionExposure.LONG_OUTDOOR_LINE
    assert updated.classification_review_state is ReviewState.USER_CONFIRMED


def test_changing_the_dvc_emits_one_update(panel: NetClassClassificationPanel, qtbot) -> None:
    panel.set_net_class(_circuit())
    with qtbot.waitSignal(panel.net_class_changed, timeout=1000) as blocker:
        index = panel._dvc_combo.findData(DecisiveVoltageClass.DVC_C)
        panel._dvc_combo.setCurrentIndex(index)
    (updated,) = blocker.args
    assert updated.decisive_voltage_class is DecisiveVoltageClass.DVC_C
    assert updated.classification_review_state is ReviewState.USER_CONFIRMED


def test_changing_the_domain_emits_one_update(panel: NetClassClassificationPanel, qtbot) -> None:
    domain = GalvanicDomain(id=uuid4(), name="Secondary side")
    panel.set_net_class(_circuit(), (domain,))
    with qtbot.waitSignal(panel.net_class_changed, timeout=1000) as blocker:
        index = panel._domain_combo.findData(domain.id)
        panel._domain_combo.setCurrentIndex(index)
    (updated,) = blocker.args
    assert updated.galvanic_domain_id == domain.id
    assert updated.classification_review_state is ReviewState.USER_CONFIRMED


def test_selecting_the_current_value_emits_nothing(
    panel: NetClassClassificationPanel, qtbot
) -> None:
    panel.set_net_class(_circuit())
    received: list[object] = []
    panel.net_class_changed.connect(received.append)
    index = panel._source_combo.findData(CircuitSourceRelationship.INTERNALLY_GENERATED)
    panel._source_combo.setCurrentIndex(index)
    assert received == []


def test_switching_to_non_circuit_nulls_every_circuit_field_in_one_update(
    panel: NetClassClassificationPanel, qtbot
) -> None:
    net = _circuit(
        source_relationship=CircuitSourceRelationship.MAINS_CONNECTED,
        connection_exposure=ConnectionExposure.LONG_OUTDOOR_LINE,
        decisive_voltage_class=DecisiveVoltageClass.DVC_C,
        galvanic_domain_id=uuid4(),
    )
    domain = GalvanicDomain(id=net.galvanic_domain_id, name="Only domain")  # type: ignore[arg-type]
    panel.set_net_class(net, (domain,))
    with qtbot.waitSignal(panel.net_class_changed, timeout=1000) as blocker:
        index = panel._type_combo.findData(NetClassType.PE_BONDED_CONDUCTIVE_PART)
        panel._type_combo.setCurrentIndex(index)
    (updated,) = blocker.args
    assert updated.net_type is NetClassType.PE_BONDED_CONDUCTIVE_PART
    assert updated.source_relationship is None
    assert updated.connection_exposure is None
    assert updated.decisive_voltage_class is None
    assert updated.galvanic_domain_id is None
    assert updated.classification_review_state is ReviewState.USER_CONFIRMED


def test_round_trip_restores_defaults_and_leaves_no_stale_value(
    panel: NetClassClassificationPanel, qtbot
) -> None:
    domain_id = uuid4()
    original = _circuit(
        source_relationship=CircuitSourceRelationship.MAINS_CONNECTED,
        connection_exposure=ConnectionExposure.LONG_OUTDOOR_LINE,
        decisive_voltage_class=DecisiveVoltageClass.DVC_C,
        galvanic_domain_id=domain_id,
    )
    domain = GalvanicDomain(id=domain_id, name="Only domain")
    panel.set_net_class(original, (domain,))

    with qtbot.waitSignal(panel.net_class_changed, timeout=1000) as away:
        index = panel._type_combo.findData(NetClassType.ACCESSIBLE_CONDUCTIVE_PART)
        panel._type_combo.setCurrentIndex(index)
    (non_circuit,) = away.args

    # As the real ProjectPage would: feed the emitted value back in before the next edit.
    panel.set_net_class(non_circuit, (domain,))

    with qtbot.waitSignal(panel.net_class_changed, timeout=1000) as back:
        index = panel._type_combo.findData(NetClassType.CIRCUIT)
        panel._type_combo.setCurrentIndex(index)
    (restored,) = back.args

    assert restored.net_type is NetClassType.CIRCUIT
    assert restored.source_relationship is CircuitSourceRelationship.INTERNALLY_GENERATED
    assert restored.connection_exposure is ConnectionExposure.INTERNAL_ONLY
    assert restored.decisive_voltage_class is DecisiveVoltageClass.NOT_EVALUATED
    assert restored.galvanic_domain_id is None
    assert restored.classification_review_state is ReviewState.USER_CONFIRMED
