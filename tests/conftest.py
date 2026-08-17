from __future__ import annotations

import json
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
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import SUPPLY_CLAUSES
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.tables import TABLE_2
from tests.rules.importer.iec62477_2022.test_axis_proposals import _voltage_limits_grid
from tests.rules.importer.iec62477_2022.test_procedure_recipes import _draft
from tests.rules.importer.iec62477_2022.test_supply_clause_recipes import _fragment


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
def draft_with_supply_fragments() -> ImportedRuleDraft:
    """A draft carrying every supply clause fragment and no authored clause facts.

    Synthetic fragments: invented neutral node text under the real recipe's fragment ids,
    which is what the clause-fact gate matches a route's authored facts against.
    """
    fragments = tuple(_fragment(spec.semantic_id) for spec in SUPPLY_CLAUSES)
    return _logged(_draft(fragments=fragments))


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
def synthetic_private_grammars(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Install a grammar where the licensed material would live, so a public test can propose.

    A grammar mapping source phrasing to typed meaning is licensed-derived and loads only from
    beside the licensed material (amendment A1), so a public checkout has none and every route
    proposes nothing. What the tests using this fixture need is a grammar *at all*: a route with
    one yields one draft per statement sentence whether or not a keyword matched, which is what
    gives the completion guard its obligations to count and the review dialog its draft rows.

    Every keyword below is a coined marker (``synth*``) that means nothing outside this file and
    occurs in no document, so no mapping from any source's phrasing to a typed meaning appears in
    this repository. Two families get rules -- the attenuation family, because it is the family the
    public surfaces are exercised through, and the reduction family, because it is the only one
    declaring a pair collection and a rule-free grammar can never reach one. Every other route gets a
    rule-free grammar, which still yields one draft per statement sentence with every dimension
    unchosen. Families and statement kinds are derived from the recipe's own public declarations,
    which is what ``_require_declared_proposal_grammars`` demands of the real file too.

    Written through the real file and the real environment variable rather than by patching the
    loader, so the loading path the maintainer depends on is the one the public suite covers.
    """
    from insulation_coordination.rules.importer.clause_fact_proposals import (
        PRIVATE_MATERIAL_DIRECTORY_VARIABLE,
        SCOPE_UNRESTRICTED,
        ClauseFactGrammar,
        ClauseKeywordRule,
        ClauseSequenceRule,
        fact_variants,
    )
    from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
        LEGACY_BRANCH_AUTHORITY_RULE_IDS,
        SUPPLY_FACT_FAMILY_BY_ROUTE,
        SUPPLY_FACT_GRAMMAR_FILE,
    )

    synthetic_rules = {
        "hf_attenuation": (
            ClauseKeywordRule(dimension="obligation", value="requirement", keywords=("synthbind",)),
            ClauseKeywordRule(dimension="obligation", value="permission", keywords=("synthallow",)),
            ClauseKeywordRule(dimension="dvc_gate", value="dvc_as", keywords=("synthgateone",)),
            ClauseKeywordRule(dimension="dvc_gate", value="dvc_b", keywords=("synthgatetwo",)),
            # The unrestricted reading of a scope dimension, spelled in the scope's own wire form.
            ClauseKeywordRule(
                dimension="evidence_kind", value=SCOPE_UNRESTRICTED, keywords=("synthevidence",)
            ),
            ClauseKeywordRule(
                dimension="comparison_required", value="true", keywords=("synthcompare",)
            ),
        ),
        # The barrier family's variants share nothing but the obligation, which makes it the family
        # where a draft can settle *only* a dimension that identifies no sentence. One rule reaching
        # the proposed variant's own scope is what lets a test have both kinds of draft at once.
        "barrier_transfer": (
            ClauseKeywordRule(dimension="obligation", value="requirement", keywords=("synthbind",)),
            ClauseKeywordRule(dimension="rated_side", value="mains", keywords=("synthmainsside",)),
            ClauseKeywordRule(
                dimension="rated_side", value="non_mains", keywords=("synthothersid",)
            ),
        ),
        # The system voltage family's proposed kind is its measure variant, and these four rules
        # settle only dimensions its *other* variant carries too. That is what a cross-kind draft
        # close needs to be selective about: the reviewer overriding a mis-proposed kind is the
        # ordinary workflow, so the shared dimensions have to be able to tell two sentences apart.
        "system_voltage": (
            ClauseKeywordRule(dimension="obligation", value="requirement", keywords=("synthbind",)),
            ClauseKeywordRule(
                dimension="input_topology", value="direct", keywords=("synthdirect",)
            ),
            ClauseKeywordRule(
                dimension="input_topology", value="rectified_dc", keywords=("synthrectified",)
            ),
            ClauseKeywordRule(dimension="purpose", value="impulse", keywords=("synthimpulse",)),
            ClauseKeywordRule(
                dimension="purpose", value="temporary_overvoltage", keywords=("synthtov",)
            ),
        ),
        # The reduction family's proposed statement kind is its permission, which is the one
        # variant in the recipe declaring an ordered pair collection. Between these rules and the
        # sequence rule below, one marked sentence settles every dimension the variant declares --
        # which is what a draft has to do before anything builds a candidate statement from it.
        "spd_reduction": (
            ClauseKeywordRule(dimension="obligation", value="permission", keywords=("synthallow",)),
            ClauseKeywordRule(
                dimension="insulation_classes", value="basic", keywords=("synthclassone",)
            ),
            ClauseKeywordRule(
                dimension="insulation_classes", value="supplementary", keywords=("synthclasstwo",)
            ),
        ),
    }
    #: Coined scale markers, deliberately declared in the same order the fact model's own
    #: vocabulary declares the designations, and gated the way the real declarations are.
    synthetic_sequences = {
        "spd_reduction": (
            ClauseSequenceRule(
                tokens=(
                    ("synthovcfour", "ovc_iv"),
                    ("synthovcthree", "ovc_iii"),
                    ("synthovctwo", "ovc_ii"),
                    ("synthovcone", "ovc_i"),
                ),
                dimension="permitted_steps",
                keywords=("synthreduce",),
            ),
        )
    }
    directory = tmp_path / "synthetic-private-material"
    directory.mkdir()
    payload = {
        route: ClauseFactGrammar(
            fact_kind=family,
            statement_kind=next(iter(fact_variants(family)), ""),
            keyword_rules=synthetic_rules.get(family, ()),
            sequence_rules=synthetic_sequences.get(family, ()),
            constants=(
                {"threshold_reference": "synthetic.threshold.route"}
                if family == "hf_attenuation"
                else {}
            ),
        ).model_dump()
        for route, family in SUPPLY_FACT_FAMILY_BY_ROUTE.items()
        if route not in LEGACY_BRANCH_AUTHORITY_RULE_IDS
    }
    path = directory / SUPPLY_FACT_GRAMMAR_FILE
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    monkeypatch.setenv(PRIVATE_MATERIAL_DIRECTORY_VARIABLE, str(directory))
    return path


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
