"""IEC 62477-1:2022 solid-insulation partial-discharge recipe and its decision projections.

Table 30 states how the partial-discharge test is performed; the subclause this module locates
states when a solid insulation owes it at all, and how the test is classified once it does. Those
are two different questions, and until now only the first had a rule: the applicability route the
package carried was projected from Table 30's test-voltage row, which answers whether a test
*voltage* has been declared. So a pair could never be told the test was required.

The subclause states its condition as two quantities, each compared against a stated threshold and
joined by *and*. Both thresholds are licensed values, so both are read from the reviewed fragment's
own node text at import time and neither is declared here, in a semantic identifier, or in a test --
the same rule the annex's frequency bounds follow in ``high_frequency``.

Layout facts only: page, bboxes, root shapes, and neutral identifiers. The regions were measured
with ``pdfplumber`` against the licensed printing and the extractor was run over them before they
were written down. Three regions of running prose, one per paragraph, because a paragraph region
extracts as one node: the condition, the definition of the second quantity, and the classification.
Merged into one region the three readings would share one text and neither rule could cite the
sentence it rests on. The subclause's opening line and its two test bullets are outside every
region -- they state the impulse and AC or DC tests, which are the sibling subclause's and their own
procedures' -- and so is its closing paragraph, which states a design requirement on double
insulation rather than anything about this test.
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
    ClauseSegmentSpec,
    StandardIdentity,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids

# The supply recipe already owns these helpers. Importing them keeps one definition of "this
# fragment is mine" and of the shape refusal rather than a second copy that could drift.
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
    _fail,
    _proposal,
    _require_own_fragment,
    _require_shape,
)

#: The test's classification, projected as its own route: whether the same insulation owes the
#: test as a type test, as a sample test, or as both. Its own rule rather than two more outputs on
#: the applicability rule, because the two questions take different inputs -- a consumer that
#: cannot say how many layers the insulation has can still ask whether the test is required, and
#: one rule carrying both would refuse to answer either.
CLASSIFICATION_ID = f"{ids.TEST_SOLID_INSULATION_PARTIAL_DISCHARGE}.classification"

#: Measured with pdfplumber against the licensed document. The x range excludes the licence
#: watermark columns at either margin.
PARTIAL_DISCHARGE_CLAUSES: tuple[ClauseAuditSpec, ...] = (
    ClauseAuditSpec(
        semantic_id=ids.TEST_SOLID_INSULATION_PARTIAL_DISCHARGE,
        clause="4.4.7.10.3",
        segments=tuple(
            ClauseSegmentSpec(
                page_number=77,
                expected_bbox=bbox,
                expected_root_kind="paragraph",
            )
            for bbox in (
                (65.0, 163.0, 535.0, 208.0),
                (65.0, 213.0, 535.0, 246.0),
                (65.0, 251.0, 535.0, 296.0),
            )
        ),
        output_kind="decision",
        #: A clause that declares routes declares all of them, this one's own decision included.
        projected_rule_ids=(ids.TEST_SOLID_INSULATION_PARTIAL_DISCHARGE, CLASSIFICATION_ID),
    ),
)

#: Reviewed structural contract: the condition, the derived quantity's definition, and the
#: classification, one paragraph node each.
_SHAPE = ("paragraph", "paragraph", "paragraph")

#: Which node states what. Positional, because the order is the reading order the segments
#: declare, and a fragment whose nodes moved is a shape surprise the check above already refuses.
_CONDITION_NODE = 0
_STRESS_DEFINITION_NODE = 1
_CLASSIFICATION_NODE = 2

#: The recurring-peak working voltage across the insulation, in volts.
_PEAK_INPUT = "working_voltage_recurring_peak_v"
#: The voltage stress on the insulation: the input above divided by the distance between the two
#: parts of different potential, which is what the fragment's second node defines it as. Resolving
#: that division is the consumer's -- this rule states the threshold it is compared against.
_STRESS_INPUT = "voltage_stress_v_per_mm"
_STRESS_UNIT = "V/mm"
#: Whether the insulation consists of a single layer of material, which is the only condition the
#: classification is stated on.
_SINGLE_LAYER_INPUT = "insulation_is_single_layer_of_material"

_TEST_REQUIRED_OUTPUT = "partial_discharge_test_required"
_TYPE_TEST_OUTPUT = "type_test_required"
_SAMPLE_TEST_OUTPUT = "sample_test_required"

#: One reviewed quantity and its unit, as the clause writes it: a number, then a voltage unit,
#: optionally per unit length. The quantities are never declared here; only the shape of the pair
#: is, and which of the two conditions a pair belongs to is read off its unit rather than off its
#: position, so a source that stated them the other way round still projects correctly.
_QUANTITY_PAIR = re.compile(r"([0-9]+(?:[.,][0-9]+)?)[  ]*(k?V(?:/mm)?)\b")
_VOLTAGE_UNIT_SCALES = {"V": 1, "kV": 1_000, "V/mm": 1, "kV/mm": 1_000}


def _thresholds(fragment: RawClauseFragment, label: str) -> tuple[Decimal, Decimal]:
    """The clause's recurring-peak threshold and its voltage-stress threshold, from the source.

    Read from the condition node alone. The other two nodes state no quantity of this kind, and
    reading the whole fragment would let a reflowed region contribute a third pair that silently
    displaced one of these two.
    """

    by_unit: dict[str, list[Decimal]] = {"": [], "/mm": []}
    text = fragment.nodes[_CONDITION_NODE].raw_text
    for quantity, unit in _QUANTITY_PAIR.findall(text):
        by_unit["/mm" if unit.endswith("/mm") else ""].append(
            Decimal(quantity.replace(",", ".")) * _VOLTAGE_UNIT_SCALES[unit]
        )
    if [len(values) for values in by_unit.values()] != [1, 1]:
        _fail(f"{label} expected one reviewed voltage threshold and one voltage-stress threshold")
    return by_unit[""][0], by_unit["/mm"][0]


def _applicability(fragment: RawClauseFragment, label: str) -> DecisionRule:
    """Whether a solid insulation owes the partial-discharge test in addition to the other two.

    Two rows, in the order the source states them: the condition it states the obligation under,
    and then everything else. The second row is the first read from the other side -- the source
    adds this test to the two above it only where both quantities exceed their thresholds, so an
    insulation that exceeds neither is not owed it -- and it is what makes the rule answerable
    rather than leaving a settled "no" unreachable the way a settled "yes" was.

    Both conditions sit in one row because the source joins them with *and*: as two rows,
    first-match-wins would let either alone decide.

    Scope is **not** an input here. Which constructions this subclause covers is stated by its own
    heading and routed to by the general subclause above it, so a rule asking for a protective
    means would be answering a question this region does not state. The consumer settles the scope
    before it asks, exactly as it already does.
    """

    peak_threshold, stress_threshold = _thresholds(fragment, label)
    source = fragment.nodes[_CONDITION_NODE].source
    exceeds = (
        Matcher(input=_PEAK_INPUT, op="range", minimum=peak_threshold, minimum_inclusive=False),
        Matcher(input=_STRESS_INPUT, op="range", minimum=stress_threshold, minimum_inclusive=False),
    )
    return DecisionRule(
        id=ids.TEST_SOLID_INSULATION_PARTIAL_DISCHARGE,
        inputs=(
            DecisionInput(name=_PEAK_INPUT, kind="numeric", unit="V"),
            DecisionInput(name=_STRESS_INPUT, kind="numeric", unit=_STRESS_UNIT),
        ),
        outputs=(DecisionOutput(name=_TEST_REQUIRED_OUTPUT, kind="boolean"),),
        rows=(
            DecisionRow(
                matchers=exceeds,
                values=(DecisionValue(name=_TEST_REQUIRED_OUTPUT, boolean=True),),
                source=source,
            ),
            DecisionRow(
                matchers=(
                    Matcher(input=_PEAK_INPUT, op="any"),
                    Matcher(input=_STRESS_INPUT, op="any"),
                ),
                values=(DecisionValue(name=_TEST_REQUIRED_OUTPUT, boolean=False),),
                source=source,
            ),
        ),
        # Numeric inputs, so the coverage check cannot prove exhaustiveness; the catch-all row
        # above is what makes every pair of quantities reach an answer.
        exhaustive=False,
        source=fragment.source,
    )


def _classification(fragment: RawClauseFragment) -> DecisionRule:
    """How the partial-discharge test is classified, once it is owed.

    The source states the type test unconditionally and adds the sample test under one construction
    condition, so the type-test answer is the same on both rows and only the sample test moves. Two
    rows rather than one with a wildcard, because the negative half is a reading the rule has to
    state to be answerable at all, and a wildcard row would leave it implicit.

    Exhaustive: the one input is a boolean and both of its values are stated.
    """

    source = fragment.nodes[_CLASSIFICATION_NODE].source

    def _row(*, single_layer: bool) -> DecisionRow:
        return DecisionRow(
            matchers=(Matcher(input=_SINGLE_LAYER_INPUT, op="equals", boolean=single_layer),),
            values=(
                DecisionValue(name=_TYPE_TEST_OUTPUT, boolean=True),
                DecisionValue(name=_SAMPLE_TEST_OUTPUT, boolean=single_layer),
            ),
            source=source,
        )

    return DecisionRule(
        id=CLASSIFICATION_ID,
        inputs=(DecisionInput(name=_SINGLE_LAYER_INPUT, kind="boolean"),),
        outputs=(
            DecisionOutput(name=_TYPE_TEST_OUTPUT, kind="boolean"),
            DecisionOutput(name=_SAMPLE_TEST_OUTPUT, kind="boolean"),
        ),
        rows=(_row(single_layer=False), _row(single_layer=True)),
        exhaustive=True,
        source=fragment.source,
    )


def project_solid_insulation_partial_discharge(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    _confirmed_facts: object = None,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project the subclause into its applicability decision and its classification decision."""

    label = "solid insulation partial discharge"
    _require_own_fragment(fragment, identity, ids.TEST_SOLID_INSULATION_PARTIAL_DISCHARGE, label)
    _require_shape(fragment, _SHAPE, label)
    if not fragment.nodes[_STRESS_DEFINITION_NODE].raw_text.strip():
        _fail(f"{label} expected the reviewed definition of the voltage stress")
    rules = (_applicability(fragment, label), _classification(fragment))
    return rules, tuple(_proposal(rule, "decision", fragment) for rule in rules)


CLAUSE_PROJECTORS: Mapping[str, ClauseProjector] = {
    ids.TEST_SOLID_INSULATION_PARTIAL_DISCHARGE: project_solid_insulation_partial_discharge,
}

__all__ = [
    "CLASSIFICATION_ID",
    "CLAUSE_PROJECTORS",
    "PARTIAL_DISCHARGE_CLAUSES",
    "project_solid_insulation_partial_discharge",
]
