"""What the project's supply arrangements derive for one pair, shown and never edited.

Every figure on this panel is a runtime result: the scenarios that reach this insulation, the
route they travelled, what governed before any override, what a verified override made of it,
and what the pair's insulation class asks of that. None of them has an editable control, and
none of them is written into a pair's own fields - clearing a configuration or an override
removes the figure rather than leaving it behind in an entry box.

The stages are shown separately rather than collapsed into one number because each answers a
different question a reviewer asks, and because the pair's own entry is still in charge
wherever it is the more severe of the two. Which of the two that is, is what the badge beside
"dimensioned from" says and what the warnings underneath explain: an entry above the derived
figure governs and says so, and an entry below it is superseded and names both values.

The badge is the shared :class:`~insulation_coordination.ui.help_indicator.FieldStateBadge`
that every other provenance in this application is shown through, so a derived value reads
here exactly as an inherited or overridden one reads in the editor beside it.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from insulation_coordination.calculation.stress_propagation import (
    EffectivePairStressResolution,
    TemporaryOvervoltageSource,
)
from insulation_coordination.domain.enums import Provenance
from insulation_coordination.domain.project import EffectiveCase, Project
from insulation_coordination.domain.supply import DerivedSupplyScenario
from insulation_coordination.domain.topology import GalvanicBarrier
from insulation_coordination.ui.help_indicator import FieldStateBadge
from insulation_coordination.ui.voltage_guidance import VoltageGuidanceId

#: Shown for a stage that has no value, so the row stays and reads as "nothing reached here"
#: rather than vanishing and reading as "not part of this calculation".
EMPTY_VALUE = "—"

#: Shown while the project enables no supply arrangement at all. It is not an error: it is the
#: state every project that predates the feature is in, and the one a user returns to.
NO_DERIVATION_TEXT = (
    "No supply arrangement is enabled for this project, so this pair is dimensioned from its "
    "own entries and the project defaults."
)

#: The stage labels, in the order a reader follows them from the supply to the insulation.
ROW_LABELS = (
    "Relationship",
    "Source scenarios",
    "Propagation path",
    "Local domain impulse",
    "Transferred impulse",
    "Governing before override",
    "Verified effective impulse",
    "Insulation-treated impulse",
    "Temporary overvoltage",
    "Source rules",
)

DIMENSIONED_FROM_LABEL = "Dimensioned from"

_STATE_BY_PROVENANCE = {
    Provenance.PROJECT_DEFAULT: VoltageGuidanceId.INHERITED_DEFAULT,
    Provenance.PAIR_OVERRIDE: VoltageGuidanceId.MANUAL_VALUE,
    Provenance.DERIVED_SUPPLY: VoltageGuidanceId.DERIVED_VALUE,
}


def _wrapping_label(text: str) -> QLabel:
    """A label that wraps, and that never widens the column it sits in.

    An ignored horizontal size policy is the point: these labels carry whole sentences, and a
    sentence's unwrapped width would otherwise become the pair editor's minimum width and
    squeeze every input beside it. Height still follows the width it is given.
    """

    label = QLabel(text)
    label.setWordWrap(True)
    policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
    policy.setHeightForWidth(True)
    label.setSizePolicy(policy)
    return label


def _volts(value: object) -> str:
    return EMPTY_VALUE if value is None else f"{value} V"


def _words(value: str) -> str:
    return value.replace("_", " ")


def source_scenarios_text(resolution: EffectivePairStressResolution) -> str:
    """Every scenario whose stress reaches either side of the pair, by name and rated value.

    Both the supplies entering the pair's own domains and the ones arriving across a barrier,
    because a reader asking "where does this come from" is asking about both.
    """

    scenarios: dict[UUID, DerivedSupplyScenario] = {}
    for side in (resolution.side_a, resolution.side_b):
        if side.stress is None:
            continue
        for source in (
            *side.stress.own,
            *(transfer.source for transfer in side.stress.transferred),
        ):
            scenarios.setdefault(source.scenario.configuration_id, source.scenario)
    if not scenarios:
        return EMPTY_VALUE
    return "; ".join(
        f"{scenario.configuration_name}: {scenario.rated_impulse_v} V"
        for scenario in scenarios.values()
    )


def propagation_text(resolution: EffectivePairStressResolution, project: Project) -> str:
    """The domains and barriers the governing stress crossed to reach this pair."""

    names = {domain.id: domain.name for domain in project.galvanic_domains}
    barriers = {barrier.id: barrier for barrier in project.galvanic_barriers}
    routes: list[str] = []
    for side in (resolution.side_a, resolution.side_b):
        stress = side.stress
        if stress is None:
            continue
        domain = names.get(stress.domain_id, str(stress.domain_id))
        transfer = stress.governing_transfer
        if transfer is None:
            routes.append(f"{domain}: {_words(stress.state.value)}, no barrier crossed")
            continue
        hops = " → ".join(names.get(item, str(item)) for item in transfer.domain_path)
        crossed = ", ".join(
            _barrier_text(barriers.get(item), names, item) for item in transfer.barrier_path
        )
        routes.append(
            f"{hops} across {crossed}, arriving as overvoltage category "
            f"{transfer.transferred_ovc.value}"
        )
    return "; ".join(dict.fromkeys(routes)) if routes else EMPTY_VALUE


def _barrier_text(barrier: GalvanicBarrier | None, names: Mapping[UUID, str], key: UUID) -> str:
    if barrier is None:
        return str(key)
    if barrier.description:
        return barrier.description
    return f"{names.get(barrier.domain_a_id, '?')}/{names.get(barrier.domain_b_id, '?')}"


def temporary_overvoltage_text(resolution: EffectivePairStressResolution) -> str:
    """Whether one applies, on whose authority, and why not where it does not."""

    temporary = resolution.temporary_overvoltage
    if not temporary.applies:
        return f"not applicable — {temporary.reason}"
    values = " / ".join(
        f"{value} V {basis}"
        for value, basis in ((temporary.peak_v, "peak"), (temporary.rms_v, "rms"))
        if value is not None
    )
    source = (
        "this pair's own entry"
        if temporary.source is TemporaryOvervoltageSource.PAIR_ENTRY
        else "the derived mains supply"
    )
    return f"{values or EMPTY_VALUE} from {source} — {temporary.reason}"


def source_rules_text(resolution: EffectivePairStressResolution) -> str:
    """Every semantic rule the pair's derivation read, deduplicated in the order it read them."""

    ordered = [
        *(
            scenario.source_rule_ids
            for side in (resolution.side_a, resolution.side_b)
            if side.stress is not None
            for scenario in (
                *(source.scenario for source in side.stress.own),
                *(transfer.source.scenario for transfer in side.stress.transferred),
            )
        ),
        tuple(step.semantic_rule_id for step in resolution.trace_steps),
        () if resolution.override_outcome is None else resolution.override_outcome.source_rule_ids,
    ]
    rule_ids = dict.fromkeys(rule_id for group in ordered for rule_id in group)
    return ", ".join(rule_ids) if rule_ids else EMPTY_VALUE


def derivation_rows(
    resolution: EffectivePairStressResolution,
    project: Project,
) -> tuple[tuple[str, str], ...]:
    """Every stage of one pair's resolution, paired with its label, in reading order."""

    values = (
        f"{_words(resolution.relationship.value)}, {_words(resolution.state.value)}",
        source_scenarios_text(resolution),
        propagation_text(resolution, project),
        _volts(resolution.local_domain_impulse_v),
        _volts(resolution.transferred_impulse_v),
        _volts(resolution.governing_pre_override_impulse_v),
        _volts(resolution.verified_effective_impulse_v),
        _volts(resolution.insulation_treated_impulse_v),
        temporary_overvoltage_text(resolution),
        source_rules_text(resolution),
    )
    return tuple(zip(ROW_LABELS, values, strict=True))


def dimensioned_from_state(
    effective: EffectiveCase | None,
    resolution: EffectivePairStressResolution | None,
) -> VoltageGuidanceId | None:
    """Where the impulse this pair is actually dimensioned from came from.

    A verified override is called by its own name rather than "derived": it is a value a user
    took responsibility for, and the badge that says so is the one the guidance behind it
    explains.
    """

    if effective is None or effective.impulse_v.value is None:
        return None
    provenance = effective.impulse_v.provenance
    outcome = None if resolution is None else resolution.override_outcome
    if provenance is Provenance.DERIVED_SUPPLY and outcome is not None and outcome.applied:
        return VoltageGuidanceId.VERIFIED_OVERRIDE
    return _STATE_BY_PROVENANCE[provenance]


def warnings_text(resolution: EffectivePairStressResolution | None) -> str:
    """Everything the resolution has to say, including which of two figures governs."""

    if resolution is None or not resolution.warnings:
        return ""
    return "\n".join(f"• {warning.message}" for warning in resolution.warnings)


class DerivedSupplyPanel(QWidget):
    """Read-only view of one pair's supply derivation. It edits nothing and owns no state."""

    def __init__(self) -> None:
        super().__init__()
        group = QGroupBox("Derived supply stress")
        outer = QVBoxLayout(group)

        self._notice = _wrapping_label(NO_DERIVATION_TEXT)
        outer.addWidget(self._notice)

        form = QFormLayout()
        self._values = {label: _wrapping_label(EMPTY_VALUE) for label in ROW_LABELS}
        for label, widget in self._values.items():
            form.addRow(f"{label}:", widget)

        self._dimensioned = QLabel(EMPTY_VALUE)
        self._badge = FieldStateBadge()
        dimensioned_row = QHBoxLayout()
        dimensioned_row.setContentsMargins(0, 0, 0, 0)
        dimensioned_row.addWidget(self._dimensioned)
        dimensioned_row.addWidget(self._badge)
        dimensioned_row.addStretch(1)
        container = QWidget()
        container.setLayout(dimensioned_row)
        form.addRow(f"{DIMENSIONED_FROM_LABEL}:", container)
        outer.addLayout(form)

        self._warnings = _wrapping_label("")
        self._warnings.setObjectName("_supply_warnings")
        outer.addWidget(self._warnings)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(group)

    def set_resolution(
        self,
        resolution: EffectivePairStressResolution | None,
        project: Project | None = None,
        effective: EffectiveCase | None = None,
        notice: str = "",
    ) -> None:
        """Show ``resolution``, or the reason there is none.

        ``notice`` carries whatever only the caller knows about an absent derivation - the
        rule package's refusal, most usefully. Without one, an absent resolution reads as the
        ordinary state of a project that enables no arrangement.
        """

        self._notice.setText(notice or NO_DERIVATION_TEXT)
        self._notice.setVisible(resolution is None or bool(notice))
        rows = (
            {label: EMPTY_VALUE for label in ROW_LABELS}
            if resolution is None or project is None
            else dict(derivation_rows(resolution, project))
        )
        for label, widget in self._values.items():
            widget.setText(rows[label])
        impulse = None if effective is None else effective.impulse_v.value
        self._dimensioned.setText(_volts(impulse))
        self._badge.set_state(dimensioned_from_state(effective, resolution))
        self._warnings.setText(warnings_text(resolution))

    def value_text(self, label: str) -> str:
        return self._values[label].text()

    @property
    def dimensioned_from_text(self) -> str:
        return self._dimensioned.text()

    @property
    def dimensioned_from_badge(self) -> str:
        return self._badge.text()

    @property
    def warnings(self) -> str:
        return self._warnings.text()

    @property
    def notice(self) -> str:
        return "" if self._notice.isHidden() else self._notice.text()


__all__ = [
    "DIMENSIONED_FROM_LABEL",
    "EMPTY_VALUE",
    "NO_DERIVATION_TEXT",
    "ROW_LABELS",
    "DerivedSupplyPanel",
    "derivation_rows",
    "dimensioned_from_state",
    "propagation_text",
    "source_rules_text",
    "source_scenarios_text",
    "temporary_overvoltage_text",
    "warnings_text",
]
