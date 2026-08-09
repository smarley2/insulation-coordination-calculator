"""Curve review model: local-only maintainer corrections over reviewed curves.

Every mutation delegates to the importer's correction functions, so each change
records an audited correction and resets the aggregate proposal. No source pixels
are stored; the overlay decodes the current local PDF crop in memory only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from insulation_coordination.domain.rules import (
    CurveInterpolation,
    CurvePoint,
    CurveSegment,
    CurveSegmentType,
)
from insulation_coordination.rules.importer.approval import approval_blockers
from insulation_coordination.rules.importer.extract import ImportedRuleDraft
from insulation_coordination.rules.importer.review import (
    associate_curve_trace,
    mark_proposal_reviewed,
    replace_curve_breakpoint,
    replace_curve_segment,
)

if TYPE_CHECKING:
    from insulation_coordination.ui.rules_manager import RulesManagerWindow


class CurveReviewModel:
    """Review actions over one draft's reconstructed curve rule."""

    def __init__(self, draft: ImportedRuleDraft) -> None:
        self._draft = draft

    @classmethod
    def for_window(cls, window: RulesManagerWindow) -> CurveReviewModel | None:
        """Back the model with the draft currently selected in the Rules Manager."""

        draft = window.draft
        if draft is None:
            return None
        return cls(draft)

    @property
    def draft(self) -> ImportedRuleDraft:
        return self._draft

    def set_breakpoint(
        self,
        variant_id: str,
        index: int,
        point: CurvePoint,
        *,
        actor: str,
        notes: str,
    ) -> ImportedRuleDraft:
        self._draft = replace_curve_breakpoint(
            self._draft,
            variant_id=variant_id,
            index=index,
            point=point,
            actor=actor,
            notes=notes,
        )
        return self._draft

    def set_segment(
        self,
        variant_id: str,
        index: int,
        start: int,
        end: int,
        segment_type: CurveSegmentType,
        interpolation: CurveInterpolation,
        *,
        actor: str,
        notes: str,
    ) -> ImportedRuleDraft:
        self._draft = replace_curve_segment(
            self._draft,
            variant_id=variant_id,
            index=index,
            segment=CurveSegment(
                start=start,
                end=end,
                segment_type=segment_type,
                interpolation=interpolation,
            ),
            actor=actor,
            notes=notes,
        )
        return self._draft

    def associate_trace(
        self,
        trace_id: str,
        variant_id: str,
        *,
        actor: str,
        notes: str,
    ) -> ImportedRuleDraft:
        self._draft = associate_curve_trace(
            self._draft,
            trace_id=trace_id,
            variant_id=variant_id,
            actor=actor,
            notes=notes,
        )
        return self._draft

    def review_variant(
        self,
        variant_id: str,
        *,
        actor: str,
        notes: str,
    ) -> ImportedRuleDraft:
        """Review the aggregate proposal after inspecting one variant."""

        rule = next(
            (rule for rule in self._draft.curves for v in rule.variants if v.id == variant_id),
            None,
        )
        if rule is None:
            raise ValueError(f"unknown curve variant: {variant_id}")
        self._draft = mark_proposal_reviewed(
            self._draft, rule.id, actor=actor, notes=notes
        )
        return self._draft

    @property
    def can_approve(self) -> bool:
        return not approval_blockers(self._draft)


__all__ = ["CurveReviewModel"]
