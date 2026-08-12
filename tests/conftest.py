from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from insulation_coordination.domain.rules import ApprovalRecord
from insulation_coordination.rules.importer.extract import (
    IMPORTER_VERSION,
    ImportedRuleDraft,
    RawGrid,
    _axis_proposal_sha256,
    draft_content_digest,
    propose_axis_selectors,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.tables import TABLE_2
from tests.rules.importer.iec62477_2022.test_axis_proposals import _voltage_limits_grid
from tests.rules.importer.iec62477_2022.test_procedure_recipes import _draft


def _logged(draft: ImportedRuleDraft) -> ImportedRuleDraft:
    """Stamp the one extraction audit record axis review recording requires to exist.

    Axis review corrects the draft through ``record_correction``, which refuses to correct
    a draft carrying no unique ``content:<hash>`` extraction record. Digested through the
    same function the gate re-derives, so a collection this fixture starts carrying cannot
    make its own audit record read as an unlogged change.
    """
    digest = draft_content_digest(draft)
    record = ApprovalRecord(
        action="extraction",
        actor=f"icc-importer/{IMPORTER_VERSION}",
        recorded_at=datetime.now(UTC),
        notes=f"content:{digest}",
    )
    return draft.model_copy(
        update={"manifest": draft.manifest.model_copy(update={"approval_records": (record,)})}
    )


@pytest.fixture
def voltage_limits_grid() -> RawGrid:
    """Table 2's synthetic grid, carrying the real recipe's grid id.

    Shared by ``tests/rules/importer`` and ``tests/ui``: the real id is what approval
    blockers, review recording and axis resolution all match proposals against.
    """
    return _voltage_limits_grid().model_copy(update={"id": f"raw-{TABLE_2.semantic_id}"})


@pytest.fixture
def draft_with_axis_proposals(voltage_limits_grid: RawGrid) -> ImportedRuleDraft:
    """A minimal draft carrying Table 2's synthetic grid and its proposed axis selectors."""
    proposals = propose_axis_selectors(TABLE_2, voltage_limits_grid)
    draft = _draft(voltage_limits_grid).model_copy(update={"axis_selector_proposals": proposals})
    return _logged(draft)


@pytest.fixture
def draft_with_unmatched_row(voltage_limits_grid: RawGrid) -> ImportedRuleDraft:
    """Task 3's fixture pattern, with one row position carrying no proposed reading.

    ``propose_axis_selectors`` already proves elsewhere that unrecognisable header text
    proposes nothing; reproducing that here at the proposal level -- rather than
    re-deriving it from modified header text -- keeps this grid's content, and so its
    artifact hash, identical to ``voltage_limits_grid``.
    """
    proposals = propose_axis_selectors(TABLE_2, voltage_limits_grid)
    unmatched = tuple(
        proposal.model_copy(
            update={
                "selector": None,
                "proposal_sha256": _axis_proposal_sha256(
                    proposal.grid_id, proposal.axis, proposal.index, None
                ),
            }
        )
        if proposal.axis == "row" and proposal.index == 3
        else proposal
        for proposal in proposals
    )
    draft = _draft(voltage_limits_grid).model_copy(update={"axis_selector_proposals": unmatched})
    return _logged(draft)


@pytest.fixture
def symlinks_allowed(tmp_path: Path) -> None:
    """Skip a symlink-rejection test on hosts that cannot create symlinks.

    Windows only allows this for administrators or with Developer Mode enabled,
    so the guarded behaviour is untestable rather than broken there.
    """
    probe = tmp_path / "symlink-probe"
    target = tmp_path / "symlink-probe-target"
    target.write_text("probe", encoding="utf-8")
    try:
        probe.symlink_to(target)
    except OSError as error:
        pytest.skip(f"symlinks cannot be created on this host: {error}")
    probe.unlink()
    target.unlink()
