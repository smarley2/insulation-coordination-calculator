"""IEC 62477-1:2022 reinforced spacing treatment recipes and their decision projection.

Two subclauses state how a spacing for the stronger insulation is dimensioned from the weaker
one's, and they are the last piece the calculator's own reinforced handling needs before it can
stop carrying that treatment as constants (#40 Task 4, #110). Neither states it in a table, so
neither had a clause spec and no clearance or creepage clause was extracted at all.

Layout facts only, exactly as the sibling recipes: page, bbox, root shape, and neutral
identifiers. **No factor is declared here.** A factor is licensed source content, so the reviewed
statement carries it -- authored into the maintainer's private draft -- and this module converts
it at projection. That is the same rule the supply recipe's frequency thresholds follow, which
are read from the private fragment rather than written down beside the recipe.

Each spec covers the treatment its identifier names rather than its whole subclause, the way the
propagation and barrier transfer routes already split 4.4.7.2.5 between them: the creepage
subclause's requirement paragraph and its treatment paragraph sit on either side of the table
they refer to, so the two regions are read in reading order and the table between them is
extracted by its own spec.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import get_args

from insulation_coordination.domain.rules import (
    DecisionInput,
    DecisionOutput,
    DecisionRow,
    DecisionRule,
    DecisionValue,
)
from insulation_coordination.rules.importer.clause_facts import (
    ConfirmedFacts,
    ReinforcedFactorFact,
    ReinforcedLevelStepFact,
    TreatedQuantity,
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
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.clauses import (
    ClauseStructureError,
)

#: Measured with pdfplumber against the licensed document; the x range excludes the licence
#: watermark columns at either margin.
REINFORCED_CLAUSES: tuple[ClauseAuditSpec, ...] = (
    ClauseAuditSpec(
        semantic_id=ids.CLEARANCE_REINFORCED_TREATMENT,
        clause="4.4.7.4.2",
        #: Three regions in reading order over two pages. The subclause opens at the foot of the
        #: earlier page with the sentence its list completes and the first two items, carries its
        #: last item to the head of the next page, and closes there in running prose. The first
        #: region's top edge sits between the subclause heading's last line and that opening
        #: sentence, so the list's modality is in the fragment rather than in wording no reviewer
        #: could see; the last region's bottom edge sits above the next subclause's heading.
        segments=(
            ClauseSegmentSpec(
                page_number=68,
                expected_bbox=(65.0, 733.0, 535.0, 792.0),
                expected_root_kind="bullets",
            ),
            ClauseSegmentSpec(
                page_number=69,
                expected_bbox=(65.0, 80.0, 535.0, 103.0),
                expected_root_kind="bullets",
            ),
            ClauseSegmentSpec(
                page_number=69,
                expected_bbox=(65.0, 103.0, 535.0, 155.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
    ),
    ClauseAuditSpec(
        semantic_id=ids.CREEPAGE_REINFORCED_TREATMENT,
        clause="4.4.7.5.2",
        #: Two regions of running prose separated by the subclause's own table, which its own
        #: spec extracts: the requirement region above it, the treatment region below it on a
        #: later page. Reading order, not page order, is what the segment sequence states.
        segments=(
            ClauseSegmentSpec(
                page_number=70,
                expected_bbox=(65.0, 426.0, 535.0, 470.0),
                expected_root_kind="paragraph",
            ),
            ClauseSegmentSpec(
                page_number=72,
                expected_bbox=(65.0, 80.0, 535.0, 232.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
    ),
)

#: The one fact family each treatment route's reviewed statements may belong to. Merged into the
#: recipe's route inventory by ``supply``, which is the module the review surface, the approval
#: gate and the fact editor all read: a route absent from it is unauthorable and unapprovable.
REINFORCED_FACT_FAMILY_BY_ROUTE: dict[str, str] = {
    ids.CLEARANCE_REINFORCED_TREATMENT: "reinforced_treatment",
    ids.CREEPAGE_REINFORCED_TREATMENT: "reinforced_treatment",
}

#: Reviewed structural contract per route: the node kind expected at each position, in order.
#: The clearance subclause reads as its list's lead-in, three items, and closing prose; the
#: creepage subclause reads as one paragraph on either side of its table.
_SHAPE_BY_ROUTE: dict[str, tuple[str, ...]] = {
    ids.CLEARANCE_REINFORCED_TREATMENT: ("paragraph", "bullet", "bullet", "bullet", "paragraph"),
    ids.CREEPAGE_REINFORCED_TREATMENT: ("paragraph", "paragraph"),
}

#: The consumer's question space for the insulation class, declared here rather than derived from
#: the reviewed facts: a consumer asks about a class before any statement has been authored for
#: it, and a vocabulary grown from the fact set would put that question outside the input's
#: allowed values and raise instead of answering it.
_INSULATION_CLASSES = ("functional", "basic", "supplementary", "double", "reinforced")

#: What a treatment operates on. The reviewed and consumer domains coincide here, so an
#: unrestricted reading is a wildcard.
_TREATED_QUANTITIES: tuple[str, ...] = get_args(TreatedQuantity)

#: What the treatment does. ``multiply`` scales the treated quantity by the row's factor;
#: ``next_level_in_requirement_axis`` moves the design to the next coordinate up the row axis of
#: the requirement the treatment is stated against, and scales nothing.
_TREATMENT_MODES = ("multiply", "next_level_in_requirement_axis")

#: Routes whose reviewed deferral the rule can carry as a ``reference`` output.
#:
#: Such a value has to resolve to **exactly one** rule of the approved package, and the two
#: requirement families are not alike in that respect: the clearance requirements are one table,
#: while the creepage requirements are two routes. So the clearance treatment states the axis it
#: steps along -- which is what stops #40's adapter having to name it -- and the creepage
#: treatment's deferral stays a reviewed dimension the rule cannot carry, the same disclosed
#: shape ``HfAttenuationRequirementFact.threshold_reference`` has.
#:
#: Declared per route rather than decided from whichever ids a fact set happens to hold: an
#: output tuple that appeared once a reviewer authored a particular deferral would be a schema
#: that changes with review progress.
_ROUTES_WHOSE_DEFERRAL_IS_ONE_RULE = frozenset({ids.CLEARANCE_REINFORCED_TREATMENT})

#: The name that deferral is projected under. It is the axis a step moves along, which is the one
#: thing a consumer cannot work out from the mode alone.
_AXIS_OUTPUT = "preferred_level_axis"

#: The factor a stepping row carries: the neutral element, and never a source value. Every row of
#: a decision rule must set every declared output, and a step statement states no factor -- so the
#: numeric column carries the value that changes nothing, and ``treatment_mode`` is what tells a
#: consumer which half of the answer to read. The same shape ``_NOT_REDUCED`` takes for a
#: categorical output no statement of its route fills.
_UNSCALED = Decimal(1)


def project_reinforced_treatment(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    confirmed_facts: ConfirmedFacts | None = None,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project one reinforced treatment subclause into a decision.

    One projector for both routes, because both clauses state one question -- given an insulation
    class and the quantity being treated, how is the design dimensioned -- and answer it in the
    same two shapes. Which route is being projected is read off the fragment's own identifier, so
    a fragment cannot be projected under the other route's contract.

    Every branch is a reviewed statement's: this module states no factor, no class and no
    quantity of its own, and a route with no reviewed facts refuses rather than falling back.

    The two routes' output tuples differ by one, and only where the package can honour it: see
    ``_ROUTES_WHOSE_DEFERRAL_IS_ONE_RULE``. Both state the mode and the multiplier, which is the
    whole of what a treatment does; the route whose requirement is a single rule also states the
    axis it steps along.
    """

    # Imported here rather than at module scope: ``supply`` merges this module's clause specs and
    # route inventory into the registries every consumer reads, so it imports this module, and a
    # module-scope import of it back would close that cycle. The helpers are the generic ones its
    # own projectors use, and one copy of them is the point.
    from insulation_coordination.rules.importer.recipes.iec62477_1_2022.supply import (
        _proposal,
        _require_distinct_branches,
        _require_own_fragment,
        _require_shape,
        _scope_matcher,
        _statement_source,
    )

    route = next(
        (item for item in REINFORCED_FACT_FAMILY_BY_ROUTE if fragment.id == f"raw-{item}"), None
    )
    if route is None:
        raise ValueError("reinforced treatment projection requires one of its own fragments")
    label = f"{route} reinforced treatment"
    _require_own_fragment(fragment, identity, route, label)
    _require_shape(fragment, _SHAPE_BY_ROUTE[route], label)

    facts = (confirmed_facts or ConfirmedFacts()).for_route(route)
    if not facts:
        raise ClauseStructureError(f"{label} needs reviewed clause facts for its route")
    statements = tuple(
        fact for fact in facts if isinstance(fact, ReinforcedFactorFact | ReinforcedLevelStepFact)
    )
    if len(statements) != len(facts):
        raise ValueError(f"{label} projection requires reinforced treatment facts")

    states_axis = route in _ROUTES_WHOSE_DEFERRAL_IS_ONE_RULE

    def _row(fact: ReinforcedFactorFact | ReinforcedLevelStepFact) -> DecisionRow:
        # The variant *is* the mode, so it is read once and both answers follow from it: a
        # statement carrying a factor states a multiplication, and one carrying none states the
        # step. Nothing here can spell a mode the authored statement does not state.
        factor = fact.factor if isinstance(fact, ReinforcedFactorFact) else None
        return DecisionRow(
            matchers=(
                _scope_matcher(
                    "insulation_class",
                    fact.insulation_classes,
                    _INSULATION_CLASSES,
                    _INSULATION_CLASSES,
                ),
                _scope_matcher(
                    "treated_quantity",
                    fact.treated_quantity,
                    _TREATED_QUANTITIES,
                    _TREATED_QUANTITIES,
                ),
            ),
            values=(
                DecisionValue(
                    name="treatment_mode",
                    categorical=(
                        "multiply" if factor is not None else "next_level_in_requirement_axis"
                    ),
                ),
                DecisionValue(
                    name="treatment_multiplier",
                    numeric=_UNSCALED if factor is None else Decimal(factor),
                ),
                *(
                    (DecisionValue(name=_AXIS_OUTPUT, reference=fact.requirement_reference),)
                    if states_axis
                    else ()
                ),
            ),
            source=_statement_source(fact, (fragment,)),
        )

    rows = tuple(_row(fact) for fact in statements)
    _require_distinct_branches(label, statements, rows)
    rule = DecisionRule(
        id=route,
        inputs=(
            DecisionInput(
                name="insulation_class", kind="categorical", allowed_values=_INSULATION_CLASSES
            ),
            DecisionInput(
                name="treated_quantity", kind="categorical", allowed_values=_TREATED_QUANTITIES
            ),
        ),
        outputs=(
            DecisionOutput(
                name="treatment_mode", kind="categorical", allowed_values=_TREATMENT_MODES
            ),
            DecisionOutput(name="treatment_multiplier", kind="numeric"),
            *((DecisionOutput(name=_AXIS_OUTPUT, kind="reference"),) if states_axis else ()),
        ),
        rows=rows,
        # A class or a quantity no reviewed statement covers reaches no row, rather than being
        # told by a rule that nothing needs to be done to it.
        exhaustive=False,
        source=fragment.source,
    )
    return (rule,), (_proposal(rule, "decision", fragment),)


CLAUSE_PROJECTORS: Mapping[str, ClauseProjector] = {
    ids.CLEARANCE_REINFORCED_TREATMENT: project_reinforced_treatment,
    ids.CREEPAGE_REINFORCED_TREATMENT: project_reinforced_treatment,
}

__all__ = [
    "CLAUSE_PROJECTORS",
    "REINFORCED_CLAUSES",
    "REINFORCED_FACT_FAMILY_BY_ROUTE",
    "project_reinforced_treatment",
]
