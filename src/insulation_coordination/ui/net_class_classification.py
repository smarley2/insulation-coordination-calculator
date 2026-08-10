"""The classification panel for the net currently selected on the project page.

Five questions decide what a rule package needs from a net: is it a circuit at
all, where does its voltage come from, how far does it reach outside the
enclosure, which decisive voltage class does it fall in, and which galvanic
domain is it part of. This widget only edits those five answers on one
immutable :class:`NetClass`; it holds no IEC decision logic and never derives a
value for the user - every dropdown offers the same closed set of options
regardless of what else is selected, and the guidance beside each one explains
the choice rather than making it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.domain.enums import (
    CircuitSourceRelationship,
    ConnectionExposure,
    DecisiveVoltageClass,
    NetClassType,
    ReviewState,
)
from insulation_coordination.domain.project import NetClass
from insulation_coordination.domain.topology import GalvanicDomain
from insulation_coordination.ui.help_indicator import GuidanceDialog, HelpIndicator
from insulation_coordination.ui.topology_guidance import (
    TopologyGuidanceId,
    guidance_id_for_connection_exposure,
    guidance_id_for_dvc,
    guidance_id_for_net_type,
    guidance_id_for_source_relationship,
)

#: Shown, and disabled, for a circuit-only field on a non-circuit net.
_NOT_APPLICABLE_LABEL = "N/A"

_NET_TYPE_OPTIONS: tuple[tuple[str, NetClassType], ...] = (
    ("Circuit", NetClassType.CIRCUIT),
    ("PE-bonded conductive part", NetClassType.PE_BONDED_CONDUCTIVE_PART),
    ("Accessible conductive part", NetClassType.ACCESSIBLE_CONDUCTIVE_PART),
    ("Accessible insulating surface", NetClassType.ACCESSIBLE_INSULATING_SURFACE),
)
_SOURCE_OPTIONS: tuple[tuple[str, CircuitSourceRelationship], ...] = (
    ("Mains-connected", CircuitSourceRelationship.MAINS_CONNECTED),
    ("Non-mains, externally sourced", CircuitSourceRelationship.NON_MAINS_EXTERNAL),
    ("Internally generated", CircuitSourceRelationship.INTERNALLY_GENERATED),
)
_EXPOSURE_OPTIONS: tuple[tuple[str, ConnectionExposure], ...] = (
    ("Internal only", ConnectionExposure.INTERNAL_ONLY),
    ("External local port or cable", ConnectionExposure.EXTERNAL_LOCAL_PORT_OR_CABLE),
    ("Long outdoor line", ConnectionExposure.LONG_OUTDOOR_LINE),
)
#: Exactly the four classes IEC 62477-1:2022 defines - never derived, never recommended.
_DVC_OPTIONS: tuple[tuple[str, DecisiveVoltageClass], ...] = (
    ("Not evaluated", DecisiveVoltageClass.NOT_EVALUATED),
    ("DVC A-s", DecisiveVoltageClass.DVC_AS),
    ("DVC B", DecisiveVoltageClass.DVC_B),
    ("DVC C", DecisiveVoltageClass.DVC_C),
)

_SOURCE_RELATIONSHIP_DEFAULT = NetClass.model_fields["source_relationship"].default
_CONNECTION_EXPOSURE_DEFAULT = NetClass.model_fields["connection_exposure"].default
_DECISIVE_VOLTAGE_CLASS_DEFAULT = NetClass.model_fields["decisive_voltage_class"].default


class NetClassClassificationPanel(QWidget):
    """Edits the five classification fields of one selected :class:`NetClass`.

    Emits a replacement, immutable ``NetClass`` on every edit; it never mutates the
    project itself - the caller (``ProjectPage``) is the one that knows where the edited
    net sits among the others and routes the replacement through its own update path.
    """

    net_class_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._net_class: NetClass | None = None

        group = QGroupBox("Net classification")
        form = QFormLayout(group)

        self._type_combo = QComboBox()
        self._type_help = HelpIndicator(TopologyGuidanceId.NET_TYPE_CIRCUIT)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addRow(_labelled("Net class type:", self._type_help), self._type_combo)

        self._source_combo = QComboBox()
        self._source_help = HelpIndicator(TopologyGuidanceId.SOURCE_INTERNALLY_GENERATED)
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)
        form.addRow(_labelled("Source relationship:", self._source_help), self._source_combo)

        self._exposure_combo = QComboBox()
        self._exposure_help = HelpIndicator(TopologyGuidanceId.EXPOSURE_INTERNAL_ONLY)
        self._exposure_combo.currentIndexChanged.connect(self._on_exposure_changed)
        form.addRow(_labelled("Connection exposure:", self._exposure_help), self._exposure_combo)

        self._dvc_combo = QComboBox()
        self._dvc_help = HelpIndicator(TopologyGuidanceId.DVC_NOT_EVALUATED)
        self._dvc_combo.currentIndexChanged.connect(self._on_dvc_changed)
        form.addRow(_labelled("DVC:", self._dvc_help), self._dvc_combo)

        self._domain_combo = QComboBox()
        self._domain_help = HelpIndicator(TopologyGuidanceId.GALVANIC_DOMAIN_ASSIGNMENT)
        self._domain_combo.currentIndexChanged.connect(self._on_domain_changed)
        form.addRow(_labelled("Galvanic domain:", self._domain_help), self._domain_combo)

        self._how_to_choose = QPushButton("How to choose")
        self._how_to_choose.clicked.connect(self._on_how_to_choose_clicked)
        form.addRow(self._how_to_choose)

        outer = QVBoxLayout(self)
        outer.addWidget(group)

        self._set_enabled_state(False)

    def set_net_class(
        self, net_class: NetClass | None, domains: tuple[GalvanicDomain, ...] = ()
    ) -> None:
        """Show ``net_class``'s current classification, or blank while nothing is selected."""
        self._net_class = net_class
        if net_class is None:
            self._set_enabled_state(False)
            return
        is_circuit = net_class.net_type is NetClassType.CIRCUIT

        self._fill_combo(self._type_combo, _NET_TYPE_OPTIONS, net_class.net_type, enabled=True)
        self._type_help.set_guidance(guidance_id_for_net_type(net_class.net_type))

        self._fill_combo(
            self._source_combo, _SOURCE_OPTIONS, net_class.source_relationship, enabled=is_circuit
        )
        if net_class.source_relationship is not None:
            self._source_help.set_guidance(
                guidance_id_for_source_relationship(net_class.source_relationship)
            )

        self._fill_combo(
            self._exposure_combo,
            _EXPOSURE_OPTIONS,
            net_class.connection_exposure,
            enabled=is_circuit,
        )
        if net_class.connection_exposure is not None:
            self._exposure_help.set_guidance(
                guidance_id_for_connection_exposure(net_class.connection_exposure)
            )

        self._fill_combo(
            self._dvc_combo, _DVC_OPTIONS, net_class.decisive_voltage_class, enabled=is_circuit
        )
        if net_class.decisive_voltage_class is not None:
            self._dvc_help.set_guidance(guidance_id_for_dvc(net_class.decisive_voltage_class))

        domain_options: tuple[tuple[str, UUID | None], ...] = (
            ("Unset", None),
            *((domain.name, domain.id) for domain in domains),
        )
        self._fill_combo(
            self._domain_combo, domain_options, net_class.galvanic_domain_id, enabled=is_circuit
        )

    def _set_enabled_state(self, enabled: bool) -> None:
        for widget in (
            self._type_combo,
            self._source_combo,
            self._exposure_combo,
            self._dvc_combo,
            self._domain_combo,
        ):
            widget.setEnabled(enabled)

    def _fill_combo(
        self,
        combo: QComboBox,
        options: Sequence[tuple[str, Any]],
        current: Any,
        *,
        enabled: bool,
    ) -> None:
        combo.blockSignals(True)
        combo.clear()
        if enabled:
            for label, value in options:
                combo.addItem(label, value)
            index = next(
                (
                    position
                    for position in range(combo.count())
                    if combo.itemData(position) == current
                ),
                0,
            )
            combo.setCurrentIndex(index)
        else:
            combo.addItem(_NOT_APPLICABLE_LABEL, None)
            combo.setCurrentIndex(0)
        combo.setEnabled(enabled)
        combo.blockSignals(False)

    def _on_type_changed(self, index: int) -> None:
        if self._net_class is None:
            return
        # Qt's item-data storage quietly downgrades a StrEnum to a plain str (it is a str
        # subclass), so the enum has to be rebuilt from the combo's raw value rather than
        # trusted to survive the round trip - otherwise the model would end up holding a
        # bare string where every other reader of a NetClass expects an enum member.
        new_type = NetClassType(self._type_combo.itemData(index))
        if new_type is self._net_class.net_type:
            return
        if new_type is NetClassType.CIRCUIT:
            updates: dict[str, object] = {
                "net_type": new_type,
                "source_relationship": _SOURCE_RELATIONSHIP_DEFAULT,
                "connection_exposure": _CONNECTION_EXPOSURE_DEFAULT,
                "decisive_voltage_class": _DECISIVE_VOLTAGE_CLASS_DEFAULT,
                "galvanic_domain_id": None,
            }
        else:
            updates = {
                "net_type": new_type,
                "source_relationship": None,
                "connection_exposure": None,
                "decisive_voltage_class": None,
                "galvanic_domain_id": None,
            }
        self._emit_update(**updates)

    def _on_source_changed(self, index: int) -> None:
        if self._net_class is None:
            return
        value = CircuitSourceRelationship(self._source_combo.itemData(index))
        if value is self._net_class.source_relationship:
            return
        self._emit_update(source_relationship=value)

    def _on_exposure_changed(self, index: int) -> None:
        if self._net_class is None:
            return
        value = ConnectionExposure(self._exposure_combo.itemData(index))
        if value is self._net_class.connection_exposure:
            return
        self._emit_update(connection_exposure=value)

    def _on_dvc_changed(self, index: int) -> None:
        if self._net_class is None:
            return
        value = DecisiveVoltageClass(self._dvc_combo.itemData(index))
        if value is self._net_class.decisive_voltage_class:
            return
        self._emit_update(decisive_voltage_class=value)

    def _on_domain_changed(self, index: int) -> None:
        if self._net_class is None:
            return
        value = self._domain_combo.itemData(index)
        if value == self._net_class.galvanic_domain_id:
            return
        self._emit_update(galvanic_domain_id=value)

    def _emit_update(self, **updates: object) -> None:
        if self._net_class is None:
            return
        updates["classification_review_state"] = ReviewState.USER_CONFIRMED
        new_net_class = self._net_class.model_copy(update=updates)
        self._net_class = new_net_class
        self.net_class_changed.emit(new_net_class)

    def _on_how_to_choose_clicked(self) -> None:
        dialog = GuidanceDialog(TopologyGuidanceId.CLASSIFICATION_OVERVIEW, parent=self)
        dialog.open()


def _labelled(text: str, help_indicator: HelpIndicator) -> QWidget:
    """A form label with its ⓘ beside it, matching the project page's own helper."""
    container = QWidget()
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(QLabel(text))
    row.addWidget(help_indicator)
    row.addStretch(1)
    return container
