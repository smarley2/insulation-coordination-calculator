"""The two IEC 60664 boundary clauses, and their projections into decisions.

Both recipes under ``recipes/`` for IEC 60664 extract tables, equations and mappings, and
neither extracted a clause until now. Two boundaries the calculation depends on are stated in
prose rather than in a table cell, so no axis edge and no equation can supply either:

* **Part 4's own scope.** Its opening clause states the frequency band the standard's
  dimensioning applies over. Below that band Part 4 says nothing, which is what decides
  whether a pair is dimensioned by the high-frequency routines at all. IEC 62477-1 Annex F
  states a frequency boundary too, but that is a different standard answering a different
  question, and reading it here would be a migration in name only.
* **Part 1's Annex F advisory.** A note beside the case-B clearance tables states the peak
  stress from which those tables' dimensioning no longer settles the partial-discharge
  question, and names the two ways out. Its table is keyed by the same row axis as the table
  it qualifies, so no axis edge carries the boundary either.

Layout facts only. Each locator is one page, one bounding box and one root shape, measured
with ``pdfplumber`` against the licensed printings, and the extractor was run over both
regions before the boxes were written down. Every boundary is read at import time from the
reviewed fragment's own node text and never declared here, in a semantic identifier, or in a
test -- the rule the 62477 clause recipes already follow.

The two live in one module because the two IEC 60664 recipes are standalone modules with no
package between them to hold the ownership, shape and proposal boilerplate a clause
projection needs, and because the two rules are the two halves of one question: which figure
in application code came off a licensed page.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal
from typing import NoReturn

from insulation_coordination.domain.rules import (
    DecisionInput,
    DecisionOutput,
    DecisionRow,
    DecisionRule,
    DecisionValue,
    Matcher,
)
from insulation_coordination.rules.importer.artifacts import (
    ExtractionError,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.clauses import RawClauseFragment
from insulation_coordination.rules.importer.extract import SemanticProposal
from insulation_coordination.rules.importer.identify import (
    ClauseAuditSpec,
    ClauseProjector,
    ClauseSegmentSpec,
    StandardIdentity,
)

#: Whether Part 4's dimensioning applies to a pair at all, which is the question the constant
#: in ``calculation/high_frequency.py`` answers today from a figure written into public source.
PART4_SCOPE_FREQUENCY_APPLICABILITY = "iec60664-4:scope-frequency-applicability"

#: The advisory the engine's partial-discharge warning already cites by this identifier and
#: which no package carried. Named for the table the note points a reader at, because that is
#: the name already in the tree; the clause it is read from is the note beside that table.
PARTIAL_DISCHARGE_ADVICE = "iec60664-1:f9-partial-discharge-advice"

#: Measured with pdfplumber against the licensed printing. One region: the clause's opening
#: paragraph, which is the one that states the band. The paragraphs after it restate the lower
#: bound in relation to the other parts of the series and would contribute a third and fourth
#: reading of a boundary this rule must find exactly two of.
PART4_SCOPE_CLAUSES: tuple[ClauseAuditSpec, ...] = (
    ClauseAuditSpec(
        semantic_id=PART4_SCOPE_FREQUENCY_APPLICABILITY,
        clause="1",
        segments=(
            ClauseSegmentSpec(
                page_number=17,
                expected_bbox=(65.0, 212.0, 535.0, 295.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
    ),
)

#: Measured with pdfplumber against the licensed printing, in the page numbering the recipe's
#: own offset table converts. The note is printed twice side by side, once under each of the
#: two tables it sits below; the x range takes the left column only, so the fragment holds one
#: reading rather than the same sentence twice. The bottom edge stops above the footnote
#: markers under it, which state other things and would each extract as a bullet.
PARTIAL_DISCHARGE_ADVICE_CLAUSES: tuple[ClauseAuditSpec, ...] = (
    ClauseAuditSpec(
        semantic_id=PARTIAL_DISCHARGE_ADVICE,
        clause="Annex F",
        segments=(
            ClauseSegmentSpec(
                page_number=77,
                expected_bbox=(70.0, 88.0, 320.0, 170.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
    ),
)

#: Reviewed structural contract for both: one paragraph node.
_SHAPE = ("paragraph",)

_FREQUENCY_INPUT = "frequency_hz"
_FREQUENCY_UNIT = "Hz"
_PART4_APPLIES_OUTPUT = "part4_dimensioning_applies"

_PEAK_INPUT = "steady_state_peak_v"
_PEAK_UNIT = "V"
_REVIEW_ADVISED_OUTPUT = "partial_discharge_review_advised"

#: One reviewed quantity and its unit: a number, then a unit of the kind the clause states its
#: boundary in. The quantities themselves are never declared here; only the shape of the pair
#: is, and the scale each prefix carries.
_FREQUENCY_QUANTITY = re.compile(r"([0-9]+(?:[.,][0-9]+)?)[\s ]*([kMG]?Hz)\b")
_VOLTAGE_QUANTITY = re.compile(r"([0-9]+(?:[.,][0-9]+)?)[\s ]*(k?V)\b")
_SCALES = {
    "Hz": 1,
    "kHz": 1_000,
    "MHz": 1_000_000,
    "GHz": 1_000_000_000,
    "V": 1,
    "kV": 1_000,
}


def _fail(message: str) -> NoReturn:
    raise ExtractionError(f"AMBIGUOUS_CLAUSE_STRUCTURE: {message}")


def _require_own_fragment(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    semantic_id: str,
    label: str,
) -> None:
    if fragment.id != f"raw-{semantic_id}":
        raise ValueError(f"{label} projection requires its own fragment")
    if fragment.source.standard != identity.standard or fragment.source.edition != identity.edition:
        raise ValueError(f"{label} fragment does not match its identified source")


def _quantities(
    fragment: RawClauseFragment,
    pattern: re.Pattern[str],
    expected: int,
    label: str,
) -> tuple[Decimal, ...]:
    """The clause's boundaries, in ascending order and in the base unit, from the source.

    Read from the single reviewed node, and refused unless the region states exactly the
    number of them the rule needs: a reflowed region that reached one boundary too few or one
    too many would otherwise project a confident rule around the wrong figure.
    """

    if tuple(node.kind for node in fragment.nodes) != _SHAPE:
        _fail(f"{label} expected one reviewed paragraph")
    found = tuple(
        sorted(
            Decimal(quantity.replace(",", ".")) * _SCALES[unit]
            for quantity, unit in pattern.findall(fragment.nodes[0].raw_text)
        )
    )
    if len(found) != expected:
        _fail(f"{label} expected {expected} reviewed boundary value(s), the region states another")
    return found


def _proposal(rule: DecisionRule, fragment: RawClauseFragment) -> SemanticProposal:
    return SemanticProposal(
        semantic_id=rule.id,
        rule_kind="decision",
        state="proposed",
        rule_sha256=canonical_model_sha256(rule),
        source_artifact_sha256=canonical_model_sha256(fragment),
    )


def _settled(
    *,
    rule_id: str,
    input_name: str,
    unit: str,
    output_name: str,
    inside: Matcher,
    fragment: RawClauseFragment,
) -> DecisionRule:
    """One numeric gate stated from both sides, so either answer is reachable.

    The second row is the first read from the other side. Without it a quantity outside the
    stated bound reaches no row at all, and a consumer cannot tell "the clause says no" from
    "the package does not carry this rule" -- which is the whole difference between a migrated
    boundary and a deleted one. Numeric inputs, so the coverage check cannot prove
    exhaustiveness; the catch-all row is what makes every quantity reach an answer.
    """

    source = fragment.nodes[0].source
    return DecisionRule(
        id=rule_id,
        inputs=(DecisionInput(name=input_name, kind="numeric", unit=unit),),
        outputs=(DecisionOutput(name=output_name, kind="boolean"),),
        rows=(
            DecisionRow(
                matchers=(inside,),
                values=(DecisionValue(name=output_name, boolean=True),),
                source=source,
            ),
            DecisionRow(
                matchers=(Matcher(input=input_name, op="any"),),
                values=(DecisionValue(name=output_name, boolean=False),),
                source=source,
            ),
        ),
        exhaustive=False,
        source=fragment.source,
    )


def project_part4_frequency_scope(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    _confirmed_facts: object = None,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project Part 4's scope clause into the frequency gate its band states.

    The clause states its lower bound as one the frequency has to pass and its upper bound as
    one it may reach, so the band excludes the former and includes the latter. Which of the two
    read boundaries is which comes from their magnitudes rather than from their order in the
    sentence, so a printing that stated them the other way round still projects correctly.
    """

    label = "Part 4 frequency scope"
    _require_own_fragment(fragment, identity, PART4_SCOPE_FREQUENCY_APPLICABILITY, label)
    lower, upper = _quantities(fragment, _FREQUENCY_QUANTITY, 2, label)
    rule = _settled(
        rule_id=PART4_SCOPE_FREQUENCY_APPLICABILITY,
        input_name=_FREQUENCY_INPUT,
        unit=_FREQUENCY_UNIT,
        output_name=_PART4_APPLIES_OUTPUT,
        inside=Matcher(
            input=_FREQUENCY_INPUT,
            op="range",
            minimum=lower,
            minimum_inclusive=False,
            maximum=upper,
            maximum_inclusive=True,
        ),
        fragment=fragment,
    )
    return (rule,), (_proposal(rule, fragment),)


def project_partial_discharge_advice(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    _confirmed_facts: object = None,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project the Annex F note into the advisory trigger it states.

    One input, because one is what the note conditions on: the peak stress the clearance is
    subjected to, and a boundary it reaches rather than passes. The field condition the note
    singles out is an emphasis on where the effect is worst, not a second condition, and making
    it an input would have this rule answer a question the note does not put; the consumer
    already settles the field condition before it asks. The two ways out the note names are
    prose the consumer states in its own words, not outputs: what the rule decides is whether
    the review is owed.
    """

    label = "Annex F partial-discharge advice"
    _require_own_fragment(fragment, identity, PARTIAL_DISCHARGE_ADVICE, label)
    (boundary,) = _quantities(fragment, _VOLTAGE_QUANTITY, 1, label)
    rule = _settled(
        rule_id=PARTIAL_DISCHARGE_ADVICE,
        input_name=_PEAK_INPUT,
        unit=_PEAK_UNIT,
        output_name=_REVIEW_ADVISED_OUTPUT,
        inside=Matcher(input=_PEAK_INPUT, op="range", minimum=boundary),
        fragment=fragment,
    )
    return (rule,), (_proposal(rule, fragment),)


PART4_SCOPE_PROJECTORS: Mapping[str, ClauseProjector] = {
    PART4_SCOPE_FREQUENCY_APPLICABILITY: project_part4_frequency_scope,
}
PARTIAL_DISCHARGE_ADVICE_PROJECTORS: Mapping[str, ClauseProjector] = {
    PARTIAL_DISCHARGE_ADVICE: project_partial_discharge_advice,
}

__all__ = [
    "PART4_SCOPE_CLAUSES",
    "PART4_SCOPE_FREQUENCY_APPLICABILITY",
    "PART4_SCOPE_PROJECTORS",
    "PARTIAL_DISCHARGE_ADVICE",
    "PARTIAL_DISCHARGE_ADVICE_CLAUSES",
    "PARTIAL_DISCHARGE_ADVICE_PROJECTORS",
    "project_part4_frequency_scope",
    "project_partial_discharge_advice",
]
