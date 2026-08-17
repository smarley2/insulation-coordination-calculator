"""Reviewed semantic selectors for a grid's data rows and columns.

A physical row or column position is provenance. What a consumer resolves a rule by is the
selector a maintainer confirmed for that position, which is what these models carry. No
source wording, heading or value belongs here: only the neutral vocabulary the recipe and the
runtime contract share.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.quantities import DecimalValue
from insulation_coordination.domain.rules import Identifier, NotesText
from insulation_coordination.rules.importer.artifacts import canonical_model_sha256


class DvcDesignationSelector(FrozenModel):
    """A row axis position of either DVC table.

    ``environment`` is ``not_applicable`` where the source does not split the designation, so
    every declared decision input has an answer.
    """

    selector_kind: Literal["dvc_designation"] = "dvc_designation"
    designation: Literal["dvc_as", "dvc_b", "dvc_c"]
    environment: Literal["dry", "wet_and_saltwater_wet", "not_applicable"]


class Table2QuantitySelector(FrozenModel):
    """A column axis position of Table 2.

    ``basis`` deliberately does not reuse ``FaultTimeVoltageSelector.voltage_basis``: ``dc_mean``
    is a Table 2 working-voltage quantity and the curve's ``dc`` is a Figure 5 curve basis, so a
    consumer relating them must do so through an explicit mapping. #50 pinned that enum against
    widening.
    """

    selector_kind: Literal["table2_quantity"] = "table2_quantity"
    operating_context: Literal["normal", "single_fault_or_abnormal"]
    quantity: Literal["working_voltage", "impulse_withstand", "fault_voltage"]
    basis: Literal["ac_rms", "ac_peak", "dc_mean", "ac_peak_or_dc", "not_applicable"]


class ProtectionTargetSelector(FrozenModel):
    """A column axis position of Table 3."""

    selector_kind: Literal["protection_target"] = "protection_target"
    target: Literal["accessible_part", "adjacent_circuit"]
    pe_relationship: Literal["connected_to_pe", "not_connected_to_pe", "not_applicable"]
    access_context: Literal["general_access", "service_or_restricted_access", "not_applicable"]
    person_scope: Literal["ordinary_or_skilled", "skilled_only", "not_applicable"]
    adjacent_dvc: Literal["dvc_as", "dvc_b", "dvc_c", "not_applicable"]


class FrequencyBandSelector(FrozenModel):
    """A row axis position the source states as a band rather than as one number.

    The two bounds are extracted from the position's own cells and converted to the base
    unit; nothing declares them. ``inclusive_bound`` names which end the source closes, so
    a consumer resolving a frequency that sits exactly on a boundary lands in the one band
    the source puts it in, rather than in whichever band happens to be tried first.
    """

    selector_kind: Literal["frequency_band"] = "frequency_band"
    lower_hz: DecimalValue
    upper_hz: DecimalValue
    inclusive_bound: Literal["lower", "upper", "both", "neither"]


AxisSelector = Annotated[
    DvcDesignationSelector
    | Table2QuantitySelector
    | ProtectionTargetSelector
    | FrequencyBandSelector,
    Field(discriminator="selector_kind"),
]
#: Every axis reading kind, named once so the spec, the proposal and the review dialog
#: cannot drift apart over which kinds exist.
SelectorKind = Literal[
    "dvc_designation",
    "table2_quantity",
    "protection_target",
    "frequency_band",
]


def selector_sha256(selector: AxisSelector) -> str:
    """Canonical hash of one selector, so a review can bind to the exact reading."""

    return canonical_model_sha256(selector)


class AxisSelectorProposal(FrozenModel):
    """What the recipe's grammar read at one axis position, or nothing where it has none."""

    grid_id: Identifier
    axis: Literal["row", "column"]
    index: int = Field(ge=0)
    selector: AxisSelector | None
    #: The kind every confirmed selector at this position must carry, copied from the axis
    #: spec. A reviewer-supplied position proposes no selector, so without this the review UI
    #: could not tell which editor to offer and a reviewer could pick the wrong kind and only
    #: discover it at resolution. Deliberately outside ``_axis_proposal_sha256``'s payload,
    #: which hashes the position and its reading only, so stating the kind here invalidates no
    #: existing review.
    selector_kind: SelectorKind
    proposal_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    #: Digest of exactly this position's own header cells, not the whole grid -- see
    #: ``axis_evidence_sha256``. A correction to any other cell must not disturb this.
    evidence_sha256: str = Field(pattern=r"[0-9a-f]{64}")


class AxisSelectorReview(FrozenModel):
    """Exact draft-only review of one axis position: confirmed, corrected or supplied.

    Bound to both the current proposal and the current evidence for this exact position, so a
    changed header reading, a changed grammar or a re-extracted grid drops the review and
    re-opens it -- while a correction elsewhere in the same grid does not.
    """

    grid_id: Identifier
    axis: Literal["row", "column"]
    index: int = Field(ge=0)
    proposal_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    evidence_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    confirmed_selector: AxisSelector
    actor: str = Field(min_length=1, max_length=200)
    recorded_at: datetime
    notes: NotesText


class ConfirmedAxes(FrozenModel):
    """Resolved reviewed selectors handed to a projection. Empty for specs without axis specs."""

    rows: dict[int, AxisSelector] = Field(default_factory=dict)
    columns: dict[int, AxisSelector] = Field(default_factory=dict)

    def row(self, index: int) -> AxisSelector:
        return self.rows[index]

    def column(self, index: int) -> AxisSelector:
        return self.columns[index]
