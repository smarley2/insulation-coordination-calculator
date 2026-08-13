"""IEC 62477-1:2022 clause recipes and DVC fault-applicability projection.

The recipe declares page/bbox/shape locators only. Reviewed neutral token roles map
to applicability decisions; any structure outside the reviewed roles blocks with
``AMBIGUOUS_CLAUSE_STRUCTURE`` instead of guessing.
"""

from __future__ import annotations

from insulation_coordination.domain.rules import (
    DecisionInput,
    DecisionOutput,
    DecisionRow,
    DecisionRule,
    DecisionValue,
    Matcher,
)
from insulation_coordination.rules.importer.clauses import RawClauseFragment
from insulation_coordination.rules.importer.extract import (
    SemanticProposal,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.identify import (
    ClauseAuditSpec,
    ClauseSegmentSpec,
    StandardIdentity,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.curves import CURVES

CLAUSES: tuple[ClauseAuditSpec, ...] = (
    ClauseAuditSpec(
        semantic_id=ids.DVC_FAULT_APPLICABILITY,
        clause="4.4.2",
        segments=(
            ClauseSegmentSpec(
                page_number=44,
                expected_bbox=(70.9, 664.0, 524.4, 740.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
    ),
)

#: Reviewed structural contract: the paragraph references each maintained source
#: figure at least once and no foreign figure. Engineering selector semantics come
#: from those figures' reviewed curve recipes, not guessed from paragraph prose.
_CONTRACT_REFERENCES = frozenset(f"figure-{spec.figure}" for spec in CURVES)


class ClauseStructureError(ValueError):
    """A reviewed clause fragment falls outside the declared token contract."""


def _fail(message: str) -> None:
    raise ClauseStructureError(f"AMBIGUOUS_CLAUSE_STRUCTURE: {message}")


def project_dvc_fault_applicability(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    _confirmed_facts: object = None,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project a reviewed DVC fault-applicability fragment into a typed decision."""

    if fragment.id != f"raw-{ids.DVC_FAULT_APPLICABILITY}":
        raise ValueError("DVC fault applicability projection requires its own fragment")
    if fragment.source.standard != identity.standard or fragment.source.edition != identity.edition:
        raise ValueError("DVC fault applicability fragment does not match its identified source")

    if len(fragment.nodes) != 1 or fragment.nodes[0].kind != "paragraph":
        _fail("expected one reviewed paragraph")
    references = {str(token.normalized) for token in fragment.tokens if token.kind == "reference"}
    if references != _CONTRACT_REFERENCES:
        _fail("expected the exact maintained curve-figure inventory")

    selectors = tuple(
        dict.fromkeys(
            (selector.subject, selector.voltage_basis)
            for spec in CURVES
            for selector in spec.variant_slots
        )
    )
    subjects = tuple(dict.fromkeys(subject for subject, _basis in selectors))
    voltage_bases = tuple(dict.fromkeys(basis for _subject, basis in selectors))
    rule = DecisionRule(
        id=ids.DVC_FAULT_APPLICABILITY,
        inputs=(
            DecisionInput(
                name="subject",
                kind="categorical",
                allowed_values=subjects,
            ),
            DecisionInput(
                name="voltage_basis",
                kind="categorical",
                allowed_values=voltage_bases,
            ),
        ),
        outputs=(
            DecisionOutput(name="curve_applicability", kind="boolean"),
            DecisionOutput(
                name="required_curve",
                kind="categorical",
                allowed_values=(ids.DVC_FAULT_TIME_VOLTAGE,),
            ),
        ),
        rows=tuple(
            DecisionRow(
                matchers=(
                    Matcher(input="subject", op="equals", values=(subject,)),
                    Matcher(input="voltage_basis", op="equals", values=(basis,)),
                ),
                values=(
                    DecisionValue(name="curve_applicability", boolean=True),
                    DecisionValue(
                        name="required_curve",
                        categorical=ids.DVC_FAULT_TIME_VOLTAGE,
                    ),
                ),
                source=fragment.source,
            )
            for subject, basis in selectors
        ),
        exhaustive=False,
        source=fragment.source,
    )
    proposal = SemanticProposal(
        semantic_id=rule.id,
        rule_kind="decision",
        state="proposed",
        rule_sha256=canonical_model_sha256(rule),
        source_artifact_sha256=canonical_model_sha256(fragment),
    )
    return (rule,), (proposal,)


__all__ = ["CLAUSES", "ClauseStructureError", "project_dvc_fault_applicability"]
