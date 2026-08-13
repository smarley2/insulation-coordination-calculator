"""IEC 62477-1:2022 high-frequency applicability recipe and its decision projection.

The annex's general clause states two frequency bounds: the frequency above which the
annex's design situations apply at all, and the upper bound of the annex's own scope. Both
are licensed values, so both are read from the reviewed fragment's quantity and unit tokens
at import time and neither is declared here, in a semantic identifier, or in a test.

The projected rule answers one question: which investigation governs a spacing. Below the
lower bound the main clause governs alone. Between the bounds a working-voltage-driven
spacing is investigated under the annex as well, and the greater of the two results
governs, while an impulse- or temporary-overvoltage-driven spacing stays with the main
clause. Above the annex's own upper bound nothing in the source settles the design, so the
rule says so instead of passing the design silently.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal

from insulation_coordination.domain.rules import (
    DecisionInput,
    DecisionOutput,
    DecisionRow,
    DecisionRule,
    DecisionValue,
    Matcher,
)
from insulation_coordination.rules.importer.clauses import RawClauseFragment
from insulation_coordination.rules.importer.extract import SemanticProposal
from insulation_coordination.rules.importer.identify import (
    ClauseAuditSpec,
    ClauseProjector,
    StandardIdentity,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids

# The supply recipe already owns these helpers and the unit-token scales. Importing them
# keeps one definition of "this fragment is mine" and of the frequency unit vocabulary
# rather than a second copy that could drift.
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
    _FREQUENCY_UNIT_SCALES,
    _fail,
    _matcher,
    _proposal,
    _require_own_fragment,
    _require_shape,
)

#: Measured with pdfplumber against the licensed document: the paragraph of the annex's
#: general clause that states both frequency bounds. The x range excludes the licence
#: watermark columns at either margin.
HIGH_FREQUENCY_CLAUSES: tuple[ClauseAuditSpec, ...] = (
    ClauseAuditSpec(
        semantic_id=ids.HIGH_FREQUENCY_APPLICABILITY,
        clause="F.1",
        page_number=195,
        expected_bbox=(70.7, 260.0, 524.5, 302.0),
        expected_root_kind="paragraph",
        output_kind="decision",
    ),
)

#: Reviewed structural contract: one paragraph node.
_APPLICABILITY_SHAPE = ("paragraph", 1)

#: Which spacing is being dimensioned. The four members mirror the four design situations
#: the annex lists, one each.
_INSULATION_KINDS = (
    "clearance_inhomogeneous_field",
    "clearance_homogeneous_field",
    "creepage",
    "solid_insulation",
)
#: The annex sub-clause each insulation kind is designed under. Clause designations, not
#: source wording. ``not_applicable`` names the absence of an annex situation and belongs
#: to this projection, not to the source.
_DESIGN_SITUATIONS = (
    "annex_f_2_2",
    "annex_f_2_3",
    "annex_f_3",
    "annex_f_4",
    "not_applicable",
)
_SITUATION_BY_INSULATION_KIND = dict(
    zip(_INSULATION_KINDS, _DESIGN_SITUATIONS[: len(_INSULATION_KINDS)], strict=True)
)
#: What drives the spacing under investigation. The main clause keeps the impulse and
#: temporary-overvoltage routes even above the lower bound.
_STRESS_KINDS = ("working_voltage", "impulse_withstand", "temporary_overvoltage")
_MAIN_CLAUSE_STRESS_KINDS = ("impulse_withstand", "temporary_overvoltage")
#: Which investigation governs. ``annex_f`` is declared because it is part of the answer's
#: vocabulary, but no row selects it: wherever the annex applies, the source requires the
#: greater of the annex result and the main-clause result.
_GOVERNING_RESULTS = (
    "main_clause",
    "annex_f",
    "greater_of_both",
    "engineering_review_required",
)
_FREQUENCY_INPUT = "working_voltage_frequency_hz"


#: One reviewed frequency quantity and its unit, as the clause writes it. The generic
#: tokenizer drops a unit that carries sentence punctuation, and this clause states its
#: upper bound with a trailing comma, so the pair is read from the reviewed node text --
#: the same way ``extract.py`` reads a bound out of a table's own header text. The
#: quantity is never declared here: only the shape of the pair is.
_FREQUENCY_PAIR = re.compile(r"([0-9]+(?:[.,][0-9]+)?)[  ]*([kM]?Hz)\b")


def _frequency_bounds_hz(
    fragment: RawClauseFragment,
    label: str,
) -> tuple[Decimal, Decimal]:
    """Read the clause's lower applicability bound and upper scope bound from the source."""

    values = [
        Decimal(quantity.replace(",", ".")) * _FREQUENCY_UNIT_SCALES[unit]
        for node in fragment.nodes
        for quantity, unit in _FREQUENCY_PAIR.findall(node.raw_text)
    ]
    if len(values) != 2:
        _fail(f"{label} expected exactly two reviewed frequency quantity and unit pairs")
    lower, upper = min(values), max(values)
    if lower == upper:
        _fail(f"{label} expected two distinct reviewed frequency bounds")
    return lower, upper


def project_high_frequency_applicability(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    _confirmed_facts: object = None,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project the annex's general clause into an applicability decision."""

    label = "high-frequency applicability"
    _require_own_fragment(fragment, identity, ids.HIGH_FREQUENCY_APPLICABILITY, label)
    _require_shape(fragment, _APPLICABILITY_SHAPE, label)
    lower_hz, upper_hz = _frequency_bounds_hz(fragment, label)

    def _row(
        *,
        frequency: Matcher,
        insulation_kinds: tuple[str, ...] | None,
        stress_kinds: tuple[str, ...] | None,
        required: bool,
        situation: str,
        governing: str,
    ) -> DecisionRow:
        return DecisionRow(
            matchers=(
                frequency,
                _matcher("insulation_kind", insulation_kinds),
                _matcher("stress_kind", stress_kinds),
            ),
            values=(
                DecisionValue(name="high_frequency_evaluation_required", boolean=required),
                DecisionValue(name="applicable_design_situations", categorical=situation),
                DecisionValue(name="governing_result", categorical=governing),
            ),
            source=fragment.nodes[0].source,
        )

    below = Matcher(input=_FREQUENCY_INPUT, op="range", maximum=lower_hz, maximum_inclusive=False)
    within = Matcher(input=_FREQUENCY_INPUT, op="range", minimum=lower_hz, maximum=upper_hz)
    above = Matcher(input=_FREQUENCY_INPUT, op="range", minimum=upper_hz, minimum_inclusive=False)
    rule = DecisionRule(
        id=ids.HIGH_FREQUENCY_APPLICABILITY,
        inputs=(
            DecisionInput(name=_FREQUENCY_INPUT, kind="numeric", unit="Hz"),
            DecisionInput(
                name="insulation_kind", kind="categorical", allowed_values=_INSULATION_KINDS
            ),
            DecisionInput(name="stress_kind", kind="categorical", allowed_values=_STRESS_KINDS),
        ),
        outputs=(
            DecisionOutput(name="high_frequency_evaluation_required", kind="boolean"),
            DecisionOutput(
                name="applicable_design_situations",
                kind="categorical",
                allowed_values=_DESIGN_SITUATIONS,
            ),
            DecisionOutput(
                name="governing_result",
                kind="categorical",
                allowed_values=_GOVERNING_RESULTS,
            ),
        ),
        # Row order mirrors the source: below the lower bound first, then the routes the
        # main clause keeps, then the four annex design situations, then out of scope.
        rows=(
            _row(
                frequency=below,
                insulation_kinds=None,
                stress_kinds=None,
                required=False,
                situation="not_applicable",
                governing="main_clause",
            ),
            _row(
                frequency=within,
                insulation_kinds=None,
                stress_kinds=_MAIN_CLAUSE_STRESS_KINDS,
                required=False,
                situation="not_applicable",
                governing="main_clause",
            ),
            *(
                _row(
                    frequency=within,
                    insulation_kinds=(insulation_kind,),
                    stress_kinds=("working_voltage",),
                    required=True,
                    situation=_SITUATION_BY_INSULATION_KIND[insulation_kind],
                    governing="greater_of_both",
                )
                for insulation_kind in _INSULATION_KINDS
            ),
            _row(
                frequency=above,
                insulation_kinds=None,
                stress_kinds=None,
                required=True,
                situation="not_applicable",
                governing="engineering_review_required",
            ),
        ),
        exhaustive=False,
        source=fragment.source,
    )
    return (rule,), (_proposal(rule, "decision", fragment),)


CLAUSE_PROJECTORS: Mapping[str, ClauseProjector] = {
    ids.HIGH_FREQUENCY_APPLICABILITY: project_high_frequency_applicability,
}

__all__ = [
    "CLAUSE_PROJECTORS",
    "HIGH_FREQUENCY_CLAUSES",
    "project_high_frequency_applicability",
]
