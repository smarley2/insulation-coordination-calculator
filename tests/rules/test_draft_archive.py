"""A draft under review survives a save and resume, or is refused.

Every fixture here is visibly synthetic: the drafts come from the synthetic PDFs the importer
tests build, and the authored clause facts cite invented nodes. No licensed content appears in
this module, and no ``.icdraft`` file it writes leaves ``tmp_path``.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from insulation_coordination.domain.rules import RulePackageError
from insulation_coordination.rules.archive import MAX_ARCHIVE_BYTES
from insulation_coordination.rules.draft_archive import (
    ARCHIVE_MEMBERS,
    DRAFT_FIELDS,
    ResumedDraft,
    load_rule_draft,
    write_rule_draft,
)
from insulation_coordination.rules.importer import recipes as recipe_registry
from insulation_coordination.rules.importer.approval import (
    _require_logged_content,
    approval_blockers,
    record_correction,
)
from insulation_coordination.rules.importer.clause_facts import (
    CitedNode,
    ClauseFactCompletion,
    ClauseFactReview,
    SystemVoltageFact,
    evidence_sha256,
)
from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.review import (
    accept_raw_grid,
    build_reviewed_draft,
    draft_review_digest,
    mark_proposal_reviewed,
)
from tests.rules.test_importer import (
    _accept_all_source_artifacts,
    _compound_draft,
    _test_recipes,
)

_RECORDED_AT = datetime(2026, 2, 3, tzinfo=UTC)


@pytest.fixture(autouse=True)
def injected_recipes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recipe_registry, "RECIPES", _test_recipes())


def _source_pdfs(tmp_path: Path) -> tuple[Path, ...]:
    return (tmp_path / "part1.pdf", tmp_path / "part4.pdf", tmp_path / "part62477.pdf")


def _pdf_paths(draft: ImportedRuleDraft, paths: tuple[Path, ...]) -> dict[str, Path]:
    digests = {hashlib.sha256(path.read_bytes()).hexdigest(): path for path in paths}
    return {identity.standard: digests[identity.sha256] for identity in draft.source_identities}


def _authored_clause_facts(draft: ImportedRuleDraft) -> ImportedRuleDraft:
    """Attach one authored statement and its completion record, through the audit funnel."""
    nodes = (CitedNode(fragment_id="raw-synthetic-clause", node_order=0, node_sha256="e" * 64),)
    fact = SystemVoltageFact(
        statement_index=0,
        node_references=nodes,
        obligation="requirement",
        supply_kind="mains",
        phase_system="three_phase_star",
        earthing="tn",
        input_topology="direct",
        purpose="impulse",
        measure="phase_to_earth_rms",
    )
    review = ClauseFactReview(
        rule_route="synthetic-supply-route",
        statement_index=0,
        fact=fact,
        fact_sha256=canonical_model_sha256(fact),
        evidence_sha256=evidence_sha256(nodes),
        actor="Maintainer",
        recorded_at=_RECORDED_AT,
        notes="Synthetic authored statement.",
    )
    completion = ClauseFactCompletion(
        rule_route="synthetic-supply-route",
        fragment_id="raw-synthetic-clause",
        fragment_sha256="f" * 64,
        fact_set_sha256=canonical_model_sha256(fact),
        actor="Maintainer",
        recorded_at=_RECORDED_AT,
        notes="Synthetic fact set complete.",
    )
    return record_correction(
        draft,
        draft.model_copy(
            update={
                "clause_fact_reviews": (review,),
                "clause_fact_completions": (completion,),
            }
        ),
        actor="Maintainer",
        notes="Authored synthetic clause facts",
    )


@pytest.fixture
def reviewed_draft(tmp_path: Path) -> ImportedRuleDraft:
    """A draft carrying every kind of review work an hours-long session produces."""
    draft = _compound_draft(tmp_path)
    draft = accept_raw_grid(
        draft,
        grid_id="raw-synthetic-part1-table",
        corrections={(1, 1): Decimal("1.25")},
        actor="Maintainer",
        notes="Retyped the unclear cell",
    )
    draft = _accept_all_source_artifacts(draft)
    draft = build_reviewed_draft(draft, actor="Maintainer", notes="Projected reviewed content")
    draft = mark_proposal_reviewed(
        draft,
        draft.semantic_proposals[0].semantic_id,
        actor="Maintainer",
        notes="Reviewed the projected rule.",
    )
    return _authored_clause_facts(draft)


def _saved(tmp_path: Path, draft: ImportedRuleDraft) -> tuple[Path, dict[str, Path]]:
    pdf_paths = _pdf_paths(draft, _source_pdfs(tmp_path))
    path = tmp_path / "under-review.icdraft"
    write_rule_draft(path, draft, pdf_paths=pdf_paths)
    return path, pdf_paths


def test_draft_members_cover_every_persisted_model_field() -> None:
    """A field the archive forgets is review work silently lost on resume."""
    persisted = {
        name for name, field in ImportedRuleDraft.model_fields.items() if not field.exclude
    }

    assert set(DRAFT_FIELDS) == persisted
    assert {"review_items", "review_resolutions", "raw_grids", "semantic_proposals"} <= persisted
    assert {"clause_fact_reviews", "clause_fact_completions", "axis_selector_reviews"} <= persisted


def test_round_trip_preserves_digest_blockers_and_counts(
    tmp_path: Path, reviewed_draft: ImportedRuleDraft
) -> None:
    path, pdf_paths = _saved(tmp_path, reviewed_draft)

    resumed = load_rule_draft(path)

    assert isinstance(resumed, ResumedDraft)
    assert resumed.draft == reviewed_draft
    assert draft_review_digest(resumed.draft) == draft_review_digest(reviewed_draft)
    assert approval_blockers(resumed.draft) == approval_blockers(reviewed_draft)
    assert len(resumed.draft.review_resolutions) == len(reviewed_draft.review_resolutions)
    assert len(approval_blockers(resumed.draft)) == len(approval_blockers(reviewed_draft))
    assert resumed.pdf_paths == pdf_paths
    # The correction chain the draft's own audit re-derives still verifies after the round trip.
    _require_logged_content(resumed.draft)


def test_round_trip_keeps_every_audit_trail_the_review_produced(
    tmp_path: Path, reviewed_draft: ImportedRuleDraft
) -> None:
    path, _ = _saved(tmp_path, reviewed_draft)

    resumed = load_rule_draft(path).draft

    assert resumed.review_resolutions == reviewed_draft.review_resolutions
    assert resumed.clause_fact_reviews == reviewed_draft.clause_fact_reviews
    assert resumed.clause_fact_completions == reviewed_draft.clause_fact_completions
    assert resumed.manifest.approval_records == reviewed_draft.manifest.approval_records
    assert {item.state for item in resumed.semantic_proposals} == {"proposed", "reviewed"}
    corrected = next(
        cell
        for grid in resumed.raw_grids
        if grid.id == "raw-synthetic-part1-table"
        for cell in grid.cells
        if (cell.row, cell.column) == (1, 1)
    )
    assert corrected.value == Decimal("1.25")
    assert corrected.parse_status == "numeric"


def test_a_resumed_draft_can_never_look_more_reviewed_than_it_was(
    tmp_path: Path, reviewed_draft: ImportedRuleDraft
) -> None:
    """An extra resolution smuggled in with a matching checksum is still refused."""
    path, _ = _saved(tmp_path, reviewed_draft)
    members = _members(path)
    resolutions = json.loads(members["draft-review_resolutions.json"])
    forged = dict(resolutions[0])
    forged["review_item_sha256"] = "a" * 64
    members["draft-review_resolutions.json"] = _canonical_json([*resolutions, forged])
    checksums = json.loads(members["checksums.json"])
    checksums["draft-review_resolutions.json"] = hashlib.sha256(
        members["draft-review_resolutions.json"]
    ).hexdigest()
    members["checksums.json"] = _canonical_json(checksums)
    _write_members(path, members)

    with pytest.raises(RulePackageError, match="recorded review digest"):
        load_rule_draft(path)


def _changed_member(members: dict[str, bytes]) -> None:
    grids = json.loads(members["draft-raw_grids.json"])
    grids[0]["id"] = "raw-tampered"
    members["draft-raw_grids.json"] = _canonical_json(grids)


def _extra_member(members: dict[str, bytes]) -> None:
    members["payload.py"] = b"open('x')"


def _missing_member(members: dict[str, bytes]) -> None:
    del members["draft-review_items.json"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (_changed_member, "checksum mismatch"),
        (_extra_member, "members"),
        (_missing_member, "members"),
    ],
)
def test_resume_refuses_a_tampered_archive(
    tmp_path: Path,
    reviewed_draft: ImportedRuleDraft,
    mutate: Callable[[dict[str, bytes]], None],
    message: str,
) -> None:
    path, _ = _saved(tmp_path, reviewed_draft)
    members = _members(path)
    mutate(members)
    _write_members(path, members)

    with pytest.raises(RulePackageError, match=message):
        load_rule_draft(path)


def test_resume_refuses_an_oversized_or_highly_compressed_archive(tmp_path: Path) -> None:
    oversized = tmp_path / "oversized.icdraft"
    with oversized.open("wb") as stream:
        stream.truncate(MAX_ARCHIVE_BYTES + 1)
    with pytest.raises(RulePackageError, match="size limit"):
        load_rule_draft(oversized)

    compressed = tmp_path / "compressed.icdraft"
    with zipfile.ZipFile(compressed, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ARCHIVE_MEMBERS:
            archive.writestr(name, b"a" * 1_000_000)
    with pytest.raises(RulePackageError, match="compression ratio"):
        load_rule_draft(compressed)


@pytest.mark.parametrize("lose_the_document", (True, False))
def test_resume_refuses_a_source_document_that_no_longer_matches(
    tmp_path: Path, reviewed_draft: ImportedRuleDraft, lose_the_document: bool
) -> None:
    path, pdf_paths = _saved(tmp_path, reviewed_draft)
    document = pdf_paths[reviewed_draft.source_identities[0].standard]
    if lose_the_document:
        document.unlink()
    else:
        document.write_bytes(document.read_bytes() + b"% appended\n")

    with pytest.raises(RulePackageError, match="missing or changed"):
        load_rule_draft(path)


def test_save_refuses_a_draft_whose_source_document_is_not_on_disk(
    tmp_path: Path, reviewed_draft: ImportedRuleDraft
) -> None:
    pdf_paths = _pdf_paths(reviewed_draft, _source_pdfs(tmp_path))
    del pdf_paths[reviewed_draft.source_identities[0].standard]

    with pytest.raises(RulePackageError, match="local source document"):
        write_rule_draft(tmp_path / "incomplete.icdraft", reviewed_draft, pdf_paths=pdf_paths)


def test_saved_draft_is_byte_deterministic_and_carries_no_document_bytes(
    tmp_path: Path, reviewed_draft: ImportedRuleDraft
) -> None:
    pdf_paths = _pdf_paths(reviewed_draft, _source_pdfs(tmp_path))
    first = tmp_path / "first.icdraft"
    second = tmp_path / "second.icdraft"

    assert write_rule_draft(first, reviewed_draft, pdf_paths=pdf_paths) == write_rule_draft(
        second, reviewed_draft, pdf_paths=pdf_paths
    )
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert set(archive.namelist()) == set(ARCHIVE_MEMBERS)
        assert {member.date_time for member in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}
        sources = json.loads(archive.read("sources.json"))
    document = pdf_paths[reviewed_draft.source_identities[0].standard]
    assert set(sources) == {identity.standard for identity in reviewed_draft.source_identities}
    assert document.read_bytes() not in first.read_bytes()
    assert not list(tmp_path.glob("*.partial"))


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode()


def _members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _write_members(path: Path, members: dict[str, bytes]) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    path.write_bytes(buffer.getvalue())
