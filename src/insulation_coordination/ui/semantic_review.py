"""Semantic proposal review model backing the Rules Manager review surfaces.

Local-only maintainer workflow: proposal state, typed provenance, and correction or
review actions delegate to the importer's review/approval APIs. No source text or
values are cached here; the model reads the immutable draft on every call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import (
    Identifier,
    RuleKind,
    SourceReference,
)
from insulation_coordination.rules.importer.approval import (
    ApprovalError,
    approval_blockers,
    record_correction,
)
from insulation_coordination.rules.importer.extract import (
    ImportedRuleDraft,
    SemanticProposal,
)
from insulation_coordination.rules.importer.review import (
    mark_proposal_reviewed,
    proposal_for,
)

if TYPE_CHECKING:
    from insulation_coordination.ui.rules_manager import RulesManagerWindow


class ProposalSummary(FrozenModel):
    semantic_id: Identifier
    rule_kind: RuleKind
    state: str
    rule_sha256: str
    source_artifact_sha256: str
    source: SourceReference


@dataclass(frozen=True)
class SourceTarget:
    """Typed jump target for one proposal's source location."""

    document_id: str
    page: int | None
    clause: str | None
    bbox: tuple[float, float, float, float] | None


def _rule_source(draft: ImportedRuleDraft, proposal: SemanticProposal) -> SourceReference:
    for kind, rules in (
        ("table", draft.tables),
        ("formula", draft.formulas),
        ("mapping", draft.mappings),
        ("decision", draft.decisions),
        ("procedure", draft.procedures),
        ("guidance", draft.guidance),
        ("curve", draft.curves),
    ):
        if kind != proposal.rule_kind:
            continue
        for rule in rules:
            if rule.id == proposal.semantic_id:
                return rule.source
    raise KeyError(f"no typed rule for proposal {proposal.semantic_id}")


class SemanticReviewModel:
    """Review actions over one imported draft's semantic proposals."""

    def __init__(self, draft: ImportedRuleDraft) -> None:
        self._draft = draft

    @classmethod
    def for_window(cls, window: RulesManagerWindow) -> SemanticReviewModel | None:
        """Back the model with the draft currently selected in the Rules Manager."""

        draft = window.draft
        if draft is None:
            return None
        return cls(draft)

    @property
    def draft(self) -> ImportedRuleDraft:
        return self._draft

    @property
    def proposals(self) -> tuple[ProposalSummary, ...]:
        return tuple(self._summary(proposal) for proposal in self._draft.semantic_proposals)

    def proposal(self, semantic_id: str) -> ProposalSummary:
        return self._summary(proposal_for(self._draft, semantic_id))

    def correct(
        self,
        corrected: ImportedRuleDraft,
        *,
        actor: str,
        notes: str,
    ) -> ImportedRuleDraft:
        """Record one source correction; changed proposals reset to proposed."""

        self._draft = record_correction(self._draft, corrected, actor=actor, notes=notes)
        return self._draft

    def review(self, semantic_id: str, actor: str, notes: str) -> ImportedRuleDraft:
        if proposal_for(self._draft, semantic_id).rule_kind == "curve":
            raise ApprovalError("curve variants must be reviewed individually in Curve Review")
        self._draft = mark_proposal_reviewed(self._draft, semantic_id, actor=actor, notes=notes)
        return self._draft

    @property
    def can_approve(self) -> bool:
        return not approval_blockers(self._draft)

    def source_target(self, semantic_id: str) -> SourceTarget:
        proposal = proposal_for(self._draft, semantic_id)
        source = _rule_source(self._draft, proposal)
        bbox: tuple[float, float, float, float] | None = None
        # Function-local import keeps monkeypatched RECIPES visible at call time.
        from insulation_coordination.rules.importer.recipes import RECIPES

        bboxes: list[tuple[float, float, float, float]] = []
        for recipe in RECIPES:
            clause_matches = tuple(
                spec.expected_bbox for spec in recipe.clauses if spec.semantic_id == semantic_id
            )
            table_matches = tuple(
                spec.expected_bbox for spec in recipe.tables if spec.semantic_id == semantic_id
            )
            bboxes.extend(clause_matches + table_matches)
        if len(set(bboxes)) > 1:
            raise ValueError(f"conflicting recipe bboxes for {semantic_id}")
        if bboxes:
            bbox = bboxes[0]
        return SourceTarget(
            document_id=source.document_id,
            page=source.page,
            clause=source.clause,
            bbox=bbox,
        )

    def _summary(self, proposal: SemanticProposal) -> ProposalSummary:
        return ProposalSummary(
            semantic_id=proposal.semantic_id,
            rule_kind=proposal.rule_kind,
            state=proposal.state,
            rule_sha256=proposal.rule_sha256,
            source_artifact_sha256=proposal.source_artifact_sha256,
            source=_rule_source(self._draft, proposal),
        )


__all__ = ["ProposalSummary", "SemanticReviewModel", "SourceTarget"]
