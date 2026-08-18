"""IEC 62477-1:2022 supply-side clause recipes and their decision projections.

The recipe declares page/bbox/shape locators only. Every branch, input, and output
vocabulary below is an author-written neutral identifier: no source value, heading,
note, or clause prose lives in this file. A reviewed fragment whose node shape falls
outside the declared contract blocks with ``AMBIGUOUS_CLAUSE_STRUCTURE`` rather than
letting a projection guess a branch.

Each ``ClauseAuditSpec`` carries the ordered physical regions of one semantic clause, so a
projection is grounded in the whole clause rather than in whichever rectangle reached part
of it. A ported route's branch content comes from its reviewed clause facts (system voltage
resolution, verified barrier transfer, the SPD reduction and monitoring routes, HF
transformer attenuation): the fragment anchors the clause structurally and a
maintainer-authored fact states the branch. A route not yet ported still declares its branch
inventory here, the same way the DVC fault-applicability projection derives its selectors
from the maintained curve recipes.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, NoReturn, get_args

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import (
    DecisionInput,
    DecisionOutput,
    DecisionRow,
    DecisionRule,
    DecisionValue,
    GuidanceRule,
    Matcher,
    RuleKind,
    SourceReference,
)
from insulation_coordination.rules.importer.clause_fact_proposals import (
    FACT_MODELS_BY_KIND,
    ClauseFactGrammar,
    ClauseFactProposal,
    keyword_proposer,
    load_private_grammars,
    propose_clause_facts,
)
from insulation_coordination.rules.importer.clause_facts import (
    BarrierCombinedRequirementFact,
    BarrierTransferStatement,
    ConfirmedFacts,
    DimensionScope,
    HfAttenuationPermissionFact,
    HfAttenuationRequirementFact,
    OvercategoryStep,
    SpdMonitoringExemptionFact,
    SpdMonitoringRequirementFact,
    SpdMonitoringStatement,
    SpdReductionMonitoringFact,
    SpdReductionPermissionFact,
    SpdReductionStatement,
    SupplyFact,
    SystemVoltageMeasureFact,
    SystemVoltageStatement,
    scope_vocabulary,
)
from insulation_coordination.rules.importer.clauses import RawClauseFragment
from insulation_coordination.rules.importer.extract import (
    SemanticProposal,
    aggregate_artifact_sha256,
    canonical_model_sha256,
)
from insulation_coordination.rules.importer.identify import (
    ClauseAuditSpec,
    ClauseSegmentSpec,
    StandardIdentity,
)
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.clauses import (
    ClauseStructureError,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022.reinforced import (
    REINFORCED_CLAUSES,
    REINFORCED_FACT_FAMILY_BY_ROUTE,
)

#: The non-mains system voltage subclause. Its statement belongs to the same rule the mains
#: subclause states, so it is declared as that rule's evidence rather than as a second route:
#: physical pagination and clause numbering are provenance, not application semantics, and a
#: consumer still asks one ``supply.system_voltage_resolution`` question.
SUPPLY_SYSTEM_VOLTAGE_NON_MAINS = f"{ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION}.non_mains_evidence"

#: The monitoring subclause's own route. Named here rather than only where its rows are built,
#: because the reduction routes' declared grammar refers to it as the route their monitoring
#: obligation defers to.
_SPD_MONITORING_ROUTE = f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring"

#: The second rule each reduction route projects: the monitoring a degradable reducing device owes.
#: Its own rule rather than more outputs on the permission's, because the two statements scope
#: different dimensions and neither scopes the other's -- so as one row shape the permission's row
#: and the monitoring statement's row overlapped on every device that is both inside a reduction and
#: degradable, and the projector refused the pair. Two rules, each with exactly the inputs its own
#: statements scope and exactly the outputs they state, is what removes the collision.
#:
#: Distinct from ``_SPD_MONITORING_ROUTE``, which is the *SPD placement* monitoring clause's own
#: route: this one is about the device providing the reduction, and it defers to that route.
_SPD_DEVICE_MONITORING_SUFFIX = "device_monitoring"

#: Measured with pdfplumber against the licensed document; the x range excludes the
#: licence watermark columns at either margin.
SUPPLY_CLAUSES: tuple[ClauseAuditSpec, ...] = (
    ClauseAuditSpec(
        semantic_id=ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
        clause="4.4.7.1.7.1",
        #: Three regions in reading order, not one rectangle and not one per page. The
        #: subclause opens at the foot of the earlier page, continues at the head of the next,
        #: and resumes on that same later page below the region it opened there. A single
        #: rectangle reached the middle region only, so the statements before and after it were
        #: never extracted and could not be cited by any reviewed fact.
        segments=(
            #: The top edge sits between the subclause heading's last line and the list's
            #: lead-in line, measured with pdfplumber against the licensed document, so the
            #: region reaches the sentence the bullets complete and no heading. Before it did,
            #: a bullet had no finite verb anywhere in the fragment: its modality was
            #: unproposable and a reviewer had to read wording this fragment never showed.
            ClauseSegmentSpec(
                page_number=63,
                expected_bbox=(65.0, 705.0, 535.0, 792.0),
                expected_root_kind="bullets",
            ),
            ClauseSegmentSpec(
                page_number=64,
                expected_bbox=(65.0, 80.0, 535.0, 232.0),
                expected_root_kind="bullets",
            ),
            #: Running prose rather than bullets, which is why the root shape is per segment:
            #: one contract for the whole clause could not describe both.
            ClauseSegmentSpec(
                page_number=64,
                expected_bbox=(65.0, 232.0, 535.0, 382.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
        #: The clause's NOTEs become guidance rather than executable branches, and that
        #: guidance is grounded in this same fragment. A clause that declares routes declares
        #: all of them, this one's own decision included.
        projected_rule_ids=(
            ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
            f"{ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION}.guidance",
        ),
        evidence_clause_ids=(SUPPLY_SYSTEM_VOLTAGE_NON_MAINS,),
    ),
    #: The sibling subclause, its own reviewed fragment and its own evidence scope, feeding
    #: the rule above. Kept apart from that fragment rather than merged into it: a fragment
    #: whose nominal clause is one subclause must not quietly carry another's statements.
    ClauseAuditSpec(
        semantic_id=SUPPLY_SYSTEM_VOLTAGE_NON_MAINS,
        clause="4.4.7.1.7.2",
        segments=(
            ClauseSegmentSpec(
                page_number=64,
                expected_bbox=(65.0, 410.0, 535.0, 445.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
        projection_role="evidence",
    ),
    ClauseAuditSpec(
        semantic_id=ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION,
        clause="4.4.7.2.5",
        #: Two contiguous regions on one page: the scoping sentence the lettered alternatives
        #: complete, and then the alternatives. Declared as its own ``paragraph`` region rather than
        #: by lowering the list region's top edge, because a region states what its *list* reads as
        #: and this stem is prose that opens above it. Without it the fragment showed the
        #: alternatives and not the condition they hold under, so no reviewer could see from the
        #: fragment what the branches are scoped by.
        segments=(
            ClauseSegmentSpec(
                page_number=66,
                expected_bbox=(65.0, 576.0, 535.0, 632.0),
                expected_root_kind="paragraph",
            ),
            ClauseSegmentSpec(
                page_number=66,
                expected_bbox=(65.0, 632.0, 535.0, 792.0),
                expected_root_kind="bullets",
            ),
        ),
        output_kind="decision",
    ),
    ClauseAuditSpec(
        semantic_id=ids.SUPPLY_VERIFIED_BARRIER_TRANSFER,
        clause="4.4.7.2.5",
        segments=(
            ClauseSegmentSpec(
                page_number=67,
                expected_bbox=(65.0, 80.0, 535.0, 180.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
    ),
    ClauseAuditSpec(
        semantic_id=f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains",
        clause="4.4.7.2.3",
        #: One region over the whole subclause, from below its heading to above the next one.
        #: The earlier bbox opened below two of the subclause's own normative paragraphs, which
        #: were therefore reachable from no route and cited by no fact, and nothing said so. The
        #: top edge sits between the heading's last line and the first body line, and the bottom
        #: between the subclause's own trailing NOTEs and the next heading -- the same reach the
        #: barrier transfer and attenuation subclauses already declare over theirs. Measured with
        #: pdfplumber against the licensed document.
        segments=(
            ClauseSegmentSpec(
                page_number=65,
                expected_bbox=(65.0, 290.0, 535.0, 588.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
        projected_rule_ids=(
            f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains",
            f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains.{_SPD_DEVICE_MONITORING_SUFFIX}",
        ),
    ),
    ClauseAuditSpec(
        semantic_id=f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains",
        clause="4.4.7.2.4",
        #: Eight contiguous regions over two pages, alternating prose and lists in reading order.
        #: The subclause opens on the earlier page and continues on the next; the one region
        #: declared before reached a part of its later page only, so everything it states on the
        #: earlier page and most of what it states on the later one was extracted by nothing and
        #: reachable from no route. Each list is its own region because a region's declared root
        #: kind states what its list reads as, and each list's lead-in is prose above it; the last
        #: region ends above the next heading, so the subclause's own trailing NOTE comes with it as
        #: the sibling subclauses' do. Measured with pdfplumber against the licensed document.
        segments=(
            ClauseSegmentSpec(
                page_number=65,
                expected_bbox=(65.0, 608.0, 535.0, 640.0),
                expected_root_kind="paragraph",
            ),
            ClauseSegmentSpec(
                page_number=65,
                expected_bbox=(65.0, 640.0, 535.0, 700.0),
                expected_root_kind="bullets",
            ),
            ClauseSegmentSpec(
                page_number=65,
                expected_bbox=(65.0, 700.0, 535.0, 792.0),
                expected_root_kind="paragraph",
            ),
            ClauseSegmentSpec(
                page_number=66,
                expected_bbox=(65.0, 80.0, 535.0, 130.0),
                expected_root_kind="bullets",
            ),
            ClauseSegmentSpec(
                page_number=66,
                expected_bbox=(65.0, 130.0, 535.0, 165.0),
                expected_root_kind="paragraph",
            ),
            ClauseSegmentSpec(
                page_number=66,
                expected_bbox=(65.0, 165.0, 535.0, 222.0),
                expected_root_kind="bullets",
            ),
            ClauseSegmentSpec(
                page_number=66,
                expected_bbox=(65.0, 222.0, 535.0, 384.0),
                expected_root_kind="paragraph",
            ),
            ClauseSegmentSpec(
                page_number=66,
                expected_bbox=(65.0, 384.0, 535.0, 555.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
        projected_rule_ids=(
            f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains",
            f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains.{_SPD_DEVICE_MONITORING_SUFFIX}",
        ),
    ),
    # Retained as cited evidence, not as the source of the reduction rule: the monitoring
    # obligation each reduction route defers to is stated here.
    ClauseAuditSpec(
        semantic_id=f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring",
        clause="4.4.7.2.2",
        segments=(
            ClauseSegmentSpec(
                page_number=65,
                expected_bbox=(65.0, 110.0, 535.0, 258.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
        projected_rule_ids=(f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring",),
    ),
    ClauseAuditSpec(
        semantic_id=ids.SUPPLY_HF_TRANSFORMER_ATTENUATION,
        clause="4.4.7.2.6",
        segments=(
            ClauseSegmentSpec(
                page_number=67,
                expected_bbox=(65.0, 185.0, 535.0, 350.0),
                expected_root_kind="paragraph",
            ),
        ),
        output_kind="decision",
    ),
    #: The reinforced spacing treatment clauses are declared in their own module and merged
    #: here rather than restated. This tuple and the family map below are what the review
    #: surface, the approval gate and the fact editor read to know a route exists at all, so a
    #: clause-fact route outside them is unauthorable and unapprovable -- which is why every
    #: such route of this recipe joins them wherever its own recipe lives. The name is now
    #: narrower than the inventory; renaming it reaches the fact editor, so it is left to the
    #: change that owns that surface.
    *REINFORCED_CLAUSES,
)

#: Supply routes whose branch authority stays in this file rather than moving to reviewed
#: clause facts. Propagation's contract *is* an ordinal comparison over the overvoltage
#: category scale -- the ``reduce_one_level`` and ``take_more_severe_rating`` operations the
#: fact vocabulary names -- and no honest reviewed fact can express an ordinal comparison,
#: only the branches it enumerates. Porting it would therefore change behaviour, so it is
#: deliberately left here and tracked as #53C item 3 instead.
LEGACY_BRANCH_AUTHORITY_RULE_IDS = frozenset({ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION})

#: The one fact family each route's reviewed statements may belong to, by ``fact_kind``. Declared
#: beside the clause specs because it is the same reviewed reading: which clause states what kind
#: of rule. Authoring and the approval gate both enforce it, so a fact that cannot express a
#: route's branches cannot certify that route as reviewed, and a projector reading a route's facts
#: knows their type without inspecting them. Propagation is declared for completeness even though
#: it is the legacy route the gate skips.
SUPPLY_FACT_FAMILY_BY_ROUTE: dict[str, str] = {
    ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION: "system_voltage",
    SUPPLY_SYSTEM_VOLTAGE_NON_MAINS: "system_voltage",
    ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION: "propagation_step",
    ids.SUPPLY_VERIFIED_BARRIER_TRANSFER: "barrier_transfer",
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains": "spd_reduction",
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains": "spd_reduction",
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring": "spd_monitoring",
    ids.SUPPLY_HF_TRANSFORMER_ATTENUATION: "hf_attenuation",
    **REINFORCED_FACT_FAMILY_BY_ROUTE,
}


def _require_declared_fact_families(
    specs: tuple[ClauseAuditSpec, ...], families: dict[str, str]
) -> None:
    """Refuse, at import, a clause spec inventory and a fact family map that disagree.

    The approval gate blocks any declared supply route carrying no authored fact, while authoring
    and resolution both refuse a route this map forgets. A spec added without its entry is
    therefore unapprovable and unauthorable at once -- blocked for want of facts, and refused when
    a maintainer authors one -- with nothing saying so until someone tries both. The two are one
    reviewed reading, of which clause states what kind of rule, so they are checked where they are
    declared rather than trusted to stay in step.
    """

    declared = {spec.semantic_id for spec in specs}
    disagreement = declared.symmetric_difference(families)
    if disagreement:
        raise ValueError(
            f"supply clause specs and fact families disagree on: {sorted(disagreement)}"
        )


_require_declared_fact_families(SUPPLY_CLAUSES, SUPPLY_FACT_FAMILY_BY_ROUTE)

#: The concrete supply kind each route's own clause states, for every route whose fact family
#: carries a ``supply_kind`` field: system voltage's mains and non-mains subclauses, and each SPD
#: reduction subclause. The route determines this dimension structurally -- it is not a reviewed
#: choice -- so a fact naming the other concrete kind cannot state that route at all; see
#: ``clause_fact_defect``. Every such field names one concrete kind: this is the one dimension of
#: those families that is not a reviewed scope, precisely because the route settles it.
SUPPLY_FACT_SUPPLY_KIND_BY_ROUTE: dict[str, str] = {
    ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION: "mains",
    SUPPLY_SYSTEM_VOLTAGE_NON_MAINS: "non_mains",
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains": "mains",
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains": "non_mains",
}


def _require_declared_supply_kinds(
    families: dict[str, str], expected_supply_kinds: dict[str, str]
) -> None:
    """Refuse, at import, a route whose fact family carries ``supply_kind`` but declares no
    expected value here, or an expectation declared for a route whose family carries none.

    Without this a route added to a ``supply_kind``-carrying family and forgotten here would
    accept a fact naming either supply kind, the exact hole ``clause_fact_defect`` exists to
    close -- caught here rather than only at authoring time, the same way
    ``_require_declared_fact_families`` catches a forgotten family before a route can deadlock.
    """

    needs_expectation = {
        route
        for route, family in families.items()
        # Any variant of the family: a dimension the route determines structurally is stated by
        # every kind of statement that route can carry, so one variant declaring it is enough to
        # need the expectation -- and ``clause_fact_defect`` reads it off whichever variant arrives.
        if any("supply_kind" in model.model_fields for model in FACT_MODELS_BY_KIND[family])
    }
    disagreement = needs_expectation.symmetric_difference(expected_supply_kinds)
    if disagreement:
        raise ValueError(
            f"supply fact families and supply-kind expectations disagree on: {sorted(disagreement)}"
        )


_require_declared_supply_kinds(SUPPLY_FACT_FAMILY_BY_ROUTE, SUPPLY_FACT_SUPPLY_KIND_BY_ROUTE)

#: Whether the clause each barrier transfer route reads states the isolated or the unisolated case.
#: Structural scope, not a reviewed choice: the whole fragment is scoped by that one condition, so
#: every statement it carries is about it, and the isolated case is stated by a different clause
#: altogether -- the propagation route's. As a reviewed field it made a positive-isolation statement
#: authorable from the fragment that states the unisolated case, which nothing refused and the
#: private placeholder did.
#:
#: The projection reads it for every answer that follows from it -- whether the barrier is verified,
#: whether the transfer is permitted, which connection downstream this clause addresses, and whether
#: the requirement reaches a circuit connected to the combined circuit -- and ``clause_fact_defect``
#: reads it to refuse a statement naming the contradicting connection kind.
SUPPLY_FACT_ISOLATION_BY_ROUTE: dict[str, bool] = {
    ids.SUPPLY_VERIFIED_BARRIER_TRANSFER: False,
}


def _require_declared_isolation_scopes(
    families: dict[str, str], expected_isolation: dict[str, bool]
) -> None:
    """Refuse, at import, a barrier transfer route with no declared isolation scope, or one
    declared for a route of another family.

    Without it a route added to this family and forgotten here would carry no structural scope at
    all: its statements would be unrefusable and its projection would have no isolation state to
    read -- the same hole ``_require_declared_supply_kinds`` closes for the supply kind.
    """

    needs_scope = {route for route, family in families.items() if family == "barrier_transfer"}
    disagreement = needs_scope.symmetric_difference(expected_isolation)
    if disagreement:
        raise ValueError(
            f"barrier transfer routes and isolation scopes disagree on: {sorted(disagreement)}"
        )


_require_declared_isolation_scopes(SUPPLY_FACT_FAMILY_BY_ROUTE, SUPPLY_FACT_ISOLATION_BY_ROUTE)


def declared_rule_references() -> tuple[str, ...]:
    """Every id a reviewed statement may defer to, in sorted order.

    A ``RouteIdentifier`` dimension names another rule rather than restating its content, and until
    now nothing checked that the id it named existed: nothing consumes these references yet, so a
    mistyped one would have been recorded silently and surfaced only when a consumer first tried to
    follow it. This is the set ``clause_fact_defect`` refuses an unresolvable reference against, and
    the set the review dialog offers as a choice so the reviewer picks rather than recalls.

    **Every declared id, not a per-field shortlist.** Narrowing the choice to the ids plausible for
    one field would encode which rules may reference which, and no reviewed reading states that. What
    a reference must not be is a typo or an id nobody declares, and that is exactly what this
    refuses.

    Three sources, because a rule is declared in three shapes: the standard's own required semantic
    ids, the clause-fact routes -- a subclause-level route is not a required semantic id of its own --
    and each clause spec's projected rule ids, which is where a route's second projected rule is
    named.
    """

    projected = {rule_id for spec in SUPPLY_CLAUSES for rule_id in spec.projected_rule_ids}
    return tuple(sorted(ids.REQUIRED_SEMANTIC_IDS | set(SUPPLY_FACT_FAMILY_BY_ROUTE) | projected))


# --- proposal grammars ---------------------------------------------------------------
#
# Which term settles which dimension of which fact family is a mapping from the source's own
# phrasing to typed normative meaning. Amendment A1's audit judged that licensed-derived content
# however generic each half looks alone, so it is declared beside the licensed material and is not
# in this file, this package or this repository at all. What stays here is the route-to-family
# declaration above, and the check below that the private declarations agree with it.
#
# A proposal is a prefill of the authoring editor either way: a route with no declared grammar --
# because the private material is not installed, or because the route's branch authority is
# declared in this file -- offers no draft and every statement is authored by hand. That costs a
# maintainer typing and can never mis-certify a route.

#: The private file this recipe's grammars are read from, inside the licensed material folder.
#: Named for the recipe rather than for the clause it proposes from, so one file carries every
#: route of one document.
SUPPLY_FACT_GRAMMAR_FILE = "iec62477_1_2022-clause-fact-grammars.json"


def _require_declared_proposal_grammars(
    families: dict[str, str],
    legacy: frozenset[str],
    grammars: dict[str, ClauseFactGrammar],
) -> None:
    """Refuse a grammar map that disagrees with the fact families it proposes for.

    A route with no grammar silently loses every prefill while still looking authorable, and a
    grammar declared for the wrong family proposes dimensions that family does not carry. Both
    are caught on the way in, the same way ``_require_declared_fact_families`` catches a forgotten
    family before a route can deadlock.

    Applied only to a map that carries something. No private material installed means no grammar
    for any route, which is the honest degradation rather than a disagreement -- see
    ``supply_fact_proposal_grammars``.
    """

    expected = {route: family for route, family in families.items() if route not in legacy}
    disagreement = set(expected).symmetric_difference(grammars)
    if disagreement:
        raise ValueError(
            f"supply fact families and proposal grammars disagree on: {sorted(disagreement)}"
        )
    wrong_family = sorted(
        route for route, grammar in grammars.items() if grammar.fact_kind != expected[route]
    )
    if wrong_family:
        raise ValueError(
            f"supply proposal grammars state the wrong fact family for: {wrong_family}"
        )


def supply_fact_proposal_grammars() -> dict[str, ClauseFactGrammar]:
    """The grammar each non-legacy route's sentences are proposed from, or nothing at all.

    Read on every call rather than cached at import: the licensed folder is named by the
    environment, and a module-level snapshot would fix the answer to whatever was set when the
    first import happened -- which in a test session is whatever ran first.

    ponytail: no cache. A small JSON file per call is cheaper than a stale answer; add one keyed on
    the resolved path if a profile ever shows the read.
    """

    grammars = load_private_grammars(SUPPLY_FACT_GRAMMAR_FILE)
    if grammars:
        _require_declared_proposal_grammars(
            SUPPLY_FACT_FAMILY_BY_ROUTE, LEGACY_BRANCH_AUTHORITY_RULE_IDS, grammars
        )
    return grammars


def propose_supply_facts(
    fragment: RawClauseFragment, rule_route: str
) -> tuple[ClauseFactProposal, ...]:
    """Every sentence-level draft one route's fragment supports, or nothing for a route with
    no declared grammar.

    Nothing is also what every route returns while the private material is not installed, which is
    why the review surface reports *why* a route offers no draft rather than showing an empty list
    that reads as "this clause proposes nothing".

    The grammar is *one* implementation of "propose readings for this sentence" behind
    ``SentenceProposer``, and swapping or adding another changes nothing about how a draft is
    cited, indexed or authored.
    """

    grammar = supply_fact_proposal_grammars().get(rule_route)
    if grammar is None:
        return ()
    locked_supply_kind = SUPPLY_FACT_SUPPLY_KIND_BY_ROUTE.get(rule_route)
    return propose_clause_facts(
        fragment,
        rule_route=rule_route,
        fact_kind=grammar.fact_kind,
        statement_kind=grammar.variant,
        propose=keyword_proposer(grammar),
        locked={} if locked_supply_kind is None else {"supply_kind": locked_supply_kind},
    )


#: A ported projector's default when its call site supplies nothing: still refuses to
#: project, through the same "no facts for this route" check as a caller-supplied empty
#: result -- never a second, quieter way to get the old fallback.
_NO_CONFIRMED_FACTS = ConfirmedFacts()

#: Reviewed structural contract per projection: the node kind expected at each position, in
#: order. An ordered sequence rather than one (kind, count) pair because a clause spanning
#: several regions need not read as one kind throughout -- the system voltage clause is five
#: bullets and then one paragraph -- and "any kind" is the one weakening that would let a
#: reflowed clause project silently.
#: The leading paragraph is the bullet list's lead-in, extracted since the region was widened to
#: reach it. It is part of the reviewed contract, not incidental: without it the bullets carry no
#: finite verb and the fragment does not show what they complete.
_SYSTEM_VOLTAGE_SHAPE = (
    "paragraph",
    "bullet",
    "bullet",
    "bullet",
    "bullet",
    "bullet",
    "paragraph",
)
_SYSTEM_VOLTAGE_NON_MAINS_SHAPE = ("paragraph",)
#: The lettered alternatives, and before them the stem region that scopes them. The leading
#: paragraph is part of the reviewed contract rather than incidental: it is the condition every
#: alternative holds under, and a fragment showing four alternatives and not their scope is a
#: fragment nobody can check the projection against.
_PROPAGATION_SHAPE = ("paragraph", "bullet", "bullet", "bullet", "bullet")
_BARRIER_SHAPE = ("paragraph",)
_SPD_SHAPE = ("paragraph",)
_HF_TRANSFORMER_SHAPE = ("paragraph",)

#: Reviewed structural contract per SPD reduction route. Each was measured against the
#: licensed document from the fragment the recipe's own bbox extracts, so a reprint that
#: reflows any of these three clauses across a different number of nodes stops the build
#: instead of projecting a rule from a region nobody reviewed.
#: The non-mains reduction subclause reads as three lists, each opened by its own lead-in prose,
#: and then running prose -- the mains subclause's one paragraph is the exception among the three
#: rather than the rule. Its regions span two pages, so this is also the shape that would move
#: first if a reprint repaginated the subclause.
_SPD_NON_MAINS_SHAPE = (
    "paragraph",
    "bullet",
    "bullet",
    "bullet",
    "paragraph",
    "bullet",
    "bullet",
    "paragraph",
    "bullet",
    "bullet",
    "bullet",
    "paragraph",
    "paragraph",
)

_SPD_SHAPE_BY_ROUTE: dict[str, tuple[str, ...]] = {
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains": _SPD_SHAPE,
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains": _SPD_NON_MAINS_SHAPE,
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring": _SPD_SHAPE,
}


def _fail(message: str) -> NoReturn:
    raise ClauseStructureError(f"AMBIGUOUS_CLAUSE_STRUCTURE: {message}")


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


def _require_shape(
    fragment: RawClauseFragment,
    shape: tuple[str, ...],
    label: str,
) -> None:
    if tuple(node.kind for node in fragment.nodes) != shape:
        _fail(f"{label} expected {len(shape)} reviewed node(s) of kinds {shape}")


def _matcher(name: str, values: tuple[str, ...] | None) -> Matcher:
    """Match a categorical input against a declared branch, or any value."""

    if values is None:
        return Matcher(input=name, op="any")
    if len(values) == 1:
        return Matcher(input=name, op="equals", values=values)
    return Matcher(input=name, op="in", values=values)


def _matcher_value_set(matcher: Matcher) -> frozenset[str] | None:
    """The categorical value set a matcher restricts its input to, or ``None`` otherwise.

    ``None`` for a boolean or numeric/range matcher: those keep the old strict-equality
    comparison in ``_rows_overlap`` rather than a value-set intersection.
    """

    if matcher.op in ("equals", "in") and matcher.boolean is None:
        return frozenset(matcher.values)
    return None


def _rows_overlap(first: tuple[Matcher, ...], second: tuple[Matcher, ...]) -> bool:
    """Whether some input tuple both rows would match.

    Two rows overlap when, for every input, some value satisfies both matchers. An ``op="any"``
    matcher matches every value the other side matches, so it never discriminates. A categorical
    ``equals``/``in`` matcher is compared by the *set* of values it accepts rather than by
    equality: an ``in`` row that accepts several evidence kinds and an ``equals`` row that
    accepts one of the same kinds are not equal and neither is ``any``, and equality alone would
    miss that they both answer for that one kind -- the ``in`` row would shadow the ``equals``
    row over exactly the value they share. Boolean and numeric/range matchers keep strict
    equality: a boolean's two values are already fully enumerated by ``equals``, and a partial
    numeric overlap is not the hazard this guards against.
    """

    for one, other in zip(first, second, strict=True):
        if one.op == "any" or other.op == "any":
            continue
        one_values = _matcher_value_set(one)
        other_values = _matcher_value_set(other)
        if one_values is not None and other_values is not None:
            if not (one_values & other_values):
                return False
            continue
        if one != other:
            return False
    return True


def _require_distinct_branches(
    label: str,
    facts: tuple[SupplyFact, ...],
    rows: tuple[DecisionRow, ...],
    scopes: tuple[str, ...] | None = None,
) -> None:
    """Refuse two reviewed statements of one route whose branches are not disjoint.

    ``evaluate_decision`` serves the first row whose matchers fit, so two statements projecting
    overlapping matchers leave the later one shadowed over the overlap and its contradicting
    values unserved, with no error, no warning and a ``fact_set_sha256`` that covers both
    happily. That is the hazard ``_require_distinct_selectors`` refuses for two axis positions
    confirmed as the same selector.

    Overlap rather than equality, because equality catches only the narrowest case: a statement
    whose placement or purpose scope restricts nothing, and which therefore also covers a specific
    one, projects matchers that are never equal to it, and row order alone would decide which
    reading a consumer receives. Where the source really states a general rule and a special case, the
    special case's own dimension is what distinguishes them, and a set of statements this
    refuses is one whose distinguishing dimension nobody authored.

    Expressed over the projected matchers rather than over the facts, and so living here rather
    than in ``resolve_confirmed_clause_facts`` with the other refusals: which fields are branch
    dimensions and which are answers is the projector's own reading, and comparing facts would
    miss exactly the pair that matters -- two reduction statements agreeing on every dimension
    while naming different target categories.

    ``scopes`` names, per fact in the same order, which route or subclause it was reviewed
    under. A caller merging two routes' facts into one route's rows -- system voltage's mains
    and non-mains subclauses -- passes it so a collision names which subclause each colliding
    statement came from; ``statement_index`` alone is per-route and a mains statement 0 and a
    non-mains statement 0 would otherwise both report as "statement 0", naming no subclause. A
    single-route caller passes nothing and keeps the plain, statement-only message.
    """

    seen: list[tuple[tuple[Matcher, ...], int, str | None]] = []
    for index, (fact, row) in enumerate(zip(facts, rows, strict=True)):
        scope = scopes[index] if scopes is not None else None
        for matchers, statement_index, seen_scope in seen:
            if _rows_overlap(matchers, row.matchers):
                first = (
                    statement_index if seen_scope is None else f"{statement_index} ({seen_scope})"
                )
                second = (
                    fact.statement_index if scope is None else f"{fact.statement_index} ({scope})"
                )
                raise ClauseStructureError(
                    f"{label} statements {first} and {second} state branches that are not disjoint"
                )
        seen.append((row.matchers, fact.statement_index, scope))


def _proposal(
    rule: DecisionRule | GuidanceRule,
    rule_kind: RuleKind,
    *fragments: RawClauseFragment,
) -> SemanticProposal:
    """One proposal grounded in every fragment the rule was read from.

    Several fragments aggregate through ``aggregate_artifact_sha256``, which is the function the
    approval gate re-derives a proposal's current source digest with, so a rule two subclauses
    state between them goes stale when either fragment changes. One fragment aggregates to its
    own digest, so a single-clause rule is grounded exactly as before.
    """

    return SemanticProposal(
        semantic_id=rule.id,
        rule_kind=rule_kind,
        state="proposed",
        rule_sha256=canonical_model_sha256(rule),
        source_artifact_sha256=aggregate_artifact_sha256(
            tuple((item.id, canonical_model_sha256(item)) for item in fragments)
        ),
    )


# --- system voltage resolution -----------------------------------------------------

_SUPPLY_KINDS = ("mains", "non_mains")
_PHASE_SYSTEMS = (
    "three_phase_star",
    "three_phase_delta",
    "three_phase_it",
    "single_phase_it",
    "single_phase",
    "unspecified",
)
_EARTHING_ARRANGEMENTS = ("tn", "tt", "it", "unspecified")
_INPUT_TOPOLOGIES = (
    "direct",
    "rectified_dc",
    "series_rectifier_bridges",
    "isolated_secondary",
)
#: The consumer's question space for the calculation purpose, declared here and never derived
#: from the reviewed facts. A declared input's vocabulary is the question space, not the
#: reviewed answer space: several of the clause's statements restrict no purpose at all, so a
#: fact set of only those would derive an empty tuple and ``DecisionRule`` would refuse the
#: whole rule with a message about a categorical input rather than about the authoring.
_CALCULATION_PURPOSES = ("impulse", "temporary_overvoltage")

#: Which reviewed scope feeds which declared input. Every dimension gets a real matcher: two of
#: these inputs were once wired to ``op="any"`` on every row, which left them declared, asked about
#: by consumers, and unable to affect any answer.
#:
#: ``supply_kind`` is not here. It is the one dimension of this family the route determines rather
#: than the statement, so it stays one concrete value and projects as a plain equality -- see
#: ``SystemVoltageStatement`` and ``clause_fact_defect``.
_SYSTEM_VOLTAGE_SCOPES = (
    ("phase_system", "phase_system"),
    ("earthing_arrangement", "earthing"),
    ("input_topology", "input_topology"),
    ("calculation_purpose", "purpose"),
)


def _system_voltage_evidence_fragment(
    draft: object,
    identity: StandardIdentity,
    label: str,
) -> RawClauseFragment | None:
    """The non-mains subclause's fragment from the reviewed draft, or ``None`` without one.

    Read from the draft the way the preconditioning projection reads its sibling artifacts: the
    rule rests on two subclauses, and the fragment argument carries only the one whose identifier
    the rule bears. Resolution has already refused unless both scopes are reviewed and complete,
    so a draft reaching here holds both fragments; a caller supplying no draft grounds the
    proposal in the fragment it did supply.
    """

    fragments: tuple[RawClauseFragment, ...] = getattr(draft, "raw_clause_fragments", ())
    evidence = next(
        (item for item in fragments if item.id == f"raw-{SUPPLY_SYSTEM_VOLTAGE_NON_MAINS}"),
        None,
    )
    if evidence is None:
        return None
    _require_own_fragment(evidence, identity, SUPPLY_SYSTEM_VOLTAGE_NON_MAINS, label)
    _require_shape(evidence, _SYSTEM_VOLTAGE_NON_MAINS_SHAPE, label)
    return evidence


def _statement_source(
    fact: SupplyFact,
    fragments: tuple[RawClauseFragment, ...],
) -> SourceReference:
    """Where one statement was read: the first node it cites, in whichever fragment holds it.

    Two subclauses on two pages feed the system voltage rule, and one subclause's own regions span
    two pages for the non-mains reduction rule. A node keeps the page it came from either way, so a
    row citing its fragment's first node unconditionally would name a page its statement is not on
    -- which is why this is asked of every route whose fragments reach more than one page, and not
    only of the rule that reads two of them.
    """

    by_id = {item.id: item for item in fragments}
    for cited in fact.node_references:
        fragment = by_id.get(cited.fragment_id)
        node = (
            next((item for item in fragment.nodes if item.order == cited.node_order), None)
            if fragment is not None
            else None
        )
        if node is not None:
            return node.source
    return fragments[0].nodes[0].source


def _scope_matcher(
    input_name: str,
    scope: DimensionScope[Any],
    reviewed_domain: tuple[str, ...],
    consumer_domain: tuple[str, ...],
) -> Matcher:
    """Project one reviewed dimension scope onto one declared consumer input.

    ``DimensionScope[Any]`` because each family parametrizes the scope with its own vocabulary and
    the parametrizations are invariant; the reviewed domain arrives separately anyway.

    ``exact_one`` equals, ``exact_set`` is in -- one reviewed statement, one row, never one row per
    value.

    ``unrestricted`` is the one that needs both domains. It means unrestricted *within the reviewed
    semantic domain*, which is not the same as the consumer's declared domain: a consumer input
    routinely declares states no reviewed reading can name, and a bare ``op="any"`` answers for them
    because the evaluator returns true for it without inspecting the value. So the wildcard is used
    only where the two domains coincide, and otherwise an explicit ``in`` over the reviewed domain.
    The attenuation route's evidence handling was already the one correct case of this; this is that
    behaviour generalized.

    ``reviewed_domain`` is the dimension's **declared** domain -- every value its model permits --
    and never the values some authored fact set happens to contain. Deriving it from the authored
    set would shrink an unrestricted matcher as a side effect of how far review had progressed, so a
    reviewer mid-authoring would get a narrower rule than the one they read. See
    ``_reviewed_domain``, which reads the model.
    """

    if scope.mode == "unrestricted":
        if set(reviewed_domain) == set(consumer_domain):
            return Matcher(input=input_name, op="any")
        return _matcher(input_name, reviewed_domain)
    return _matcher(input_name, scope.values)


def _reviewed_domain(model: type[FrozenModel], field: str) -> tuple[str, ...]:
    """A dimension's declared domain, read from the fact model that declares it.

    Read from the model rather than written down beside the consumer vocabulary, so the two cannot
    drift: adding a value to a fact field widens this automatically, and no second list has to be
    remembered. A ``DimensionScope`` field's domain is the vocabulary it scopes, and a scalar
    field's is its own literal members.
    """

    annotation = model.model_fields[field].annotation
    scoped = scope_vocabulary(annotation)
    if scoped is not None:
        return scoped
    return tuple(value for value in get_args(annotation) if isinstance(value, str))


def _reviewed_scope_matcher(input_name: str, field: str, scope: DimensionScope[Any]) -> Matcher:
    """One reviewed scope against its declared input, with both domains looked up by field."""

    reviewed, consumer = _REVIEWED_AND_CONSUMER_DOMAINS[field]
    return _scope_matcher(input_name, scope, reviewed, consumer)


def project_system_voltage_resolution(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    draft: object = None,
    confirmed_facts: ConfirmedFacts = _NO_CONFIRMED_FACTS,
) -> tuple[tuple[DecisionRule | GuidanceRule, ...], tuple[SemanticProposal, ...]]:
    """Project the reviewed mains and non-mains system voltage subclauses into one decision.

    Every row comes from one reviewed ``SystemVoltageMeasureFact``: the clause states the branch,
    this projection only shapes it into the rule's declared inputs and outputs. A route with
    no reviewed facts refuses rather than falling back to an inventory nobody reviewed.

    The family's **applicability** statements are carried, not projected. Such a statement selects
    no measure, so it contributes no row and changes no declared output; it is still resolved and
    covered by the route's fact-set digest, which is how completion and the approval gate know the
    reviewer read it. A reviewed set of only applicability statements cannot answer the question
    this rule asks, so the projection refuses rather than emitting a rule with no rows -- a
    zero-row rule answers every consumer with silence and looks reviewed while doing it.

    Two subclauses state this one rule between them, so the facts come from two evidence
    scopes and the rule's proposal is grounded in the aggregate of both fragments. One
    ``DecisionRule`` and one ``SemanticProposal`` come out regardless: pagination and clause
    numbering are provenance, and a consumer asks one question.
    """

    label = "supply system voltage resolution"
    _require_own_fragment(fragment, identity, ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION, label)
    _require_shape(fragment, _SYSTEM_VOLTAGE_SHAPE, label)
    evidence = _system_voltage_evidence_fragment(draft, identity, label)

    mains_facts = confirmed_facts.for_route(ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION)
    evidence_facts = confirmed_facts.for_route(SUPPLY_SYSTEM_VOLTAGE_NON_MAINS)
    facts = (*mains_facts, *evidence_facts)
    if not facts:
        raise ClauseStructureError(f"{label} needs reviewed clause facts for its route")
    if not all(isinstance(fact, SystemVoltageStatement) for fact in facts):
        raise ValueError(f"{label} projection requires system voltage facts")
    # Two routes' facts share this one route's statement-index numbering, so a collision
    # between them needs its own scope named -- see `_require_distinct_branches`. Each measure
    # statement keeps the subclause it was reviewed under as it is selected, rather than being
    # matched back to a scope afterwards.
    scoped_facts = tuple(
        (route, fact)
        for route, group in (
            (ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION, mains_facts),
            (SUPPLY_SYSTEM_VOLTAGE_NON_MAINS, evidence_facts),
        )
        for fact in group
        if isinstance(fact, SystemVoltageMeasureFact)
    )
    if not scoped_facts:
        raise ClauseStructureError(
            f"{label} reviewed statements select no measure, so they cannot answer its question"
        )
    system_voltage_facts = tuple(fact for _route, fact in scoped_facts)
    scopes = tuple(route for route, _fact in scoped_facts)

    grounding = (fragment,) if evidence is None else (fragment, evidence)
    measures = tuple(dict.fromkeys(fact.measure for fact in system_voltage_facts))
    rows = tuple(
        DecisionRow(
            matchers=(
                _matcher("supply_kind", (fact.supply_kind,)),
                *(
                    _reviewed_scope_matcher(input_name, field, getattr(fact, field))
                    for input_name, field in _SYSTEM_VOLTAGE_SCOPES
                ),
            ),
            values=(DecisionValue(name="system_voltage_measure", categorical=fact.measure),),
            source=_statement_source(fact, grounding),
        )
        for fact in system_voltage_facts
    )
    _require_distinct_branches(label, system_voltage_facts, rows, scopes=scopes)

    rule = DecisionRule(
        id=ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION,
        inputs=(
            DecisionInput(name="supply_kind", kind="categorical", allowed_values=_SUPPLY_KINDS),
            DecisionInput(name="phase_system", kind="categorical", allowed_values=_PHASE_SYSTEMS),
            DecisionInput(
                name="earthing_arrangement",
                kind="categorical",
                allowed_values=_EARTHING_ARRANGEMENTS,
            ),
            DecisionInput(
                name="input_topology", kind="categorical", allowed_values=_INPUT_TOPOLOGIES
            ),
            DecisionInput(
                name="calculation_purpose",
                kind="categorical",
                allowed_values=_CALCULATION_PURPOSES,
            ),
        ),
        outputs=(
            DecisionOutput(
                name="system_voltage_measure",
                kind="categorical",
                allowed_values=measures,
            ),
        ),
        rows=rows,
        exhaustive=False,
        source=fragment.source,
    )
    guidance = GuidanceRule(
        id=f"{ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION}.guidance",
        title="System voltage resolution notes",
        summary=(
            "The source attaches NOTEs to the three-phase IT branches that relate the "
            "phase-to-artificial-neutral measure to the phase-to-phase measure and "
            "describe single-fault behaviour. They stay guidance: this projection names "
            "which measure applies and never computes one measure from another."
        ),
        warnings=(
            (
                "Read the source NOTEs in the cited clause before converting between "
                "the resolved measures."
            ),
        ),
        source=fragment.source,
    )
    return (rule, guidance), (
        _proposal(rule, "decision", *grounding),
        _proposal(guidance, "guidance", *grounding),
    )


# --- multiple source propagation ---------------------------------------------------

#: Overvoltage category designations in increasing severity. Designations, not values.
_OVERVOLTAGE_CATEGORIES = ("ovc_i", "ovc_ii", "ovc_iii", "ovc_iv")
_EVALUATED_SIDES = ("mains", "non_mains")


def _reduced_by_one_level(category: str) -> str:
    index = _OVERVOLTAGE_CATEGORIES.index(category)
    return _OVERVOLTAGE_CATEGORIES[max(index - 1, 0)]


def _more_severe(first: str, second: str) -> str:
    return max(first, second, key=_OVERVOLTAGE_CATEGORIES.index)


def project_multiple_source_propagation(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    # The legacy branch-authority route: resolution declares no facts for it, so this stays
    # the parameter every registered clause projector takes and this one never reads.
    _confirmed_facts: object = None,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project the lettered alternatives of the two-supply clause into a decision."""

    label = "supply multiple source propagation"
    _require_own_fragment(fragment, identity, ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION, label)
    _require_shape(fragment, _PROPAGATION_SHAPE, label)

    rows: list[DecisionRow] = []
    for side in _EVALUATED_SIDES:
        for mains_category in _OVERVOLTAGE_CATEGORIES:
            for non_mains_category in _OVERVOLTAGE_CATEGORIES:
                own = mains_category if side == "mains" else non_mains_category
                other = non_mains_category if side == "mains" else mains_category
                transferred = _reduced_by_one_level(other)
                rows.append(
                    DecisionRow(
                        matchers=(
                            Matcher(input="evaluated_side", op="equals", values=(side,)),
                            Matcher(
                                input="mains_overvoltage_category",
                                op="equals",
                                values=(mains_category,),
                            ),
                            Matcher(
                                input="non_mains_overvoltage_category",
                                op="equals",
                                values=(non_mains_category,),
                            ),
                            Matcher(input="galvanic_isolation_present", op="equals", boolean=True),
                        ),
                        values=(
                            DecisionValue(name="source_requirement", categorical=own),
                            DecisionValue(name="transferred_requirement", categorical=transferred),
                            DecisionValue(
                                name="governing_requirement",
                                categorical=_more_severe(own, transferred),
                            ),
                        ),
                        source=fragment.nodes[0].source,
                    )
                )
    rule = DecisionRule(
        id=ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION,
        inputs=(
            DecisionInput(
                name="evaluated_side", kind="categorical", allowed_values=_EVALUATED_SIDES
            ),
            DecisionInput(
                name="mains_overvoltage_category",
                kind="categorical",
                allowed_values=_OVERVOLTAGE_CATEGORIES,
            ),
            DecisionInput(
                name="non_mains_overvoltage_category",
                kind="categorical",
                allowed_values=_OVERVOLTAGE_CATEGORIES,
            ),
            DecisionInput(name="galvanic_isolation_present", kind="boolean"),
        ),
        outputs=tuple(
            DecisionOutput(name=name, kind="categorical", allowed_values=_OVERVOLTAGE_CATEGORIES)
            for name in (
                "source_requirement",
                "transferred_requirement",
                "governing_requirement",
            )
        ),
        rows=tuple(rows),
        # Without galvanic isolation the barrier-transfer rule governs, so this rule
        # deliberately covers no such row.
        exhaustive=False,
        source=fragment.source,
    )
    return (rule,), (_proposal(rule, "decision", fragment),)


# --- verified barrier transfer -----------------------------------------------------

_ISOLATION_EVIDENCE_KINDS = ("none", "test", "calculation", "construction")
_DOWNSTREAM_CONNECTION_KINDS = ("no_isolation", "verified_galvanic_isolation")
#: The connection downstream of a combined circuit that each isolation scope addresses. The route's
#: structural scope decides it: a clause stating the unisolated case addresses the circuit connected
#: to the combined circuit without isolation, and the isolated case's clause the one connected
#: through the barrier.
_DOWNSTREAM_CONNECTION_BY_ISOLATION = {
    False: "no_isolation",
    True: "verified_galvanic_isolation",
}


def project_verified_barrier_transfer(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    confirmed_facts: ConfirmedFacts = _NO_CONFIRMED_FACTS,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project the combined-circuit requirement of one barrier scope into a decision.

    Every row comes from one reviewed ``BarrierCombinedRequirementFact``, which is the one kind of
    statement this rule's declared outputs can carry. The family's other two kinds are carried, not
    projected: a rating-resolution statement defers each side's rating to that side's own supply
    route, and an inheritance statement states what a circuit connected to the combined circuit
    takes from it. Neither has a declared output here -- widening the contract to give them one is
    #53C item 5 -- and both are resolved and covered by the route's fact-set digest, which is how
    completion and the approval gate know the reviewer read them. A reviewed set carrying no
    combined-circuit statement cannot answer the question this rule asks, so the projection refuses
    rather than emitting a rule with no rows.

    Everything that follows from the barrier's isolation state is read from the route's declared
    structural scope rather than from a fact -- see ``SUPPLY_FACT_ISOLATION_BY_ROUTE``. That is which
    barrier the rule answers about, whether the transfer is permitted, which connection downstream
    this clause addresses, and whether the requirement reaches a circuit connected to the combined
    circuit. None of the four is independently authored content: they are one condition read four
    ways, and as a reviewed field the condition could contradict the clause it was read from.

    Nor is the evidence a statement requires: the source states no evidence kinds at all, and
    ``_ISOLATION_EVIDENCE_KINDS`` is this recipe's own question vocabulary, so authoring one would
    be inventing source content. The unisolated scope asks nothing of it, so the input is matched
    over every kind rather than over a set no statement names.
    """

    label = "supply verified barrier transfer"
    _require_own_fragment(fragment, identity, ids.SUPPLY_VERIFIED_BARRIER_TRANSFER, label)
    _require_shape(fragment, _BARRIER_SHAPE, label)

    isolation_present = SUPPLY_FACT_ISOLATION_BY_ROUTE[ids.SUPPLY_VERIFIED_BARRIER_TRANSFER]
    facts = confirmed_facts.for_route(ids.SUPPLY_VERIFIED_BARRIER_TRANSFER)
    if not facts:
        raise ClauseStructureError(f"{label} needs reviewed clause facts for its route")
    barrier_facts = tuple(fact for fact in facts if isinstance(fact, BarrierTransferStatement))
    if len(barrier_facts) != len(facts):
        raise ValueError(f"{label} projection requires barrier transfer facts")
    combined = tuple(
        fact for fact in barrier_facts if isinstance(fact, BarrierCombinedRequirementFact)
    )
    if not combined:
        raise ClauseStructureError(
            f"{label} reviewed statements state no combined circuit requirement, so they cannot "
            "answer its question"
        )

    requirements = tuple(dict.fromkeys(fact.combined_circuit_rule for fact in combined))
    rows = tuple(
        DecisionRow(
            matchers=(
                Matcher(
                    input="galvanic_isolation_verified",
                    op="equals",
                    boolean=isolation_present,
                ),
                _matcher("isolation_evidence_kind", None),
                _matcher(
                    "downstream_connection_kind",
                    (_DOWNSTREAM_CONNECTION_BY_ISOLATION[isolation_present],),
                ),
            ),
            values=(
                DecisionValue(name="transfer_permitted", boolean=isolation_present),
                DecisionValue(
                    name="combined_circuit_requirement",
                    categorical=fact.combined_circuit_rule,
                ),
                DecisionValue(
                    name="propagates_to_connected_circuits",
                    boolean=not isolation_present,
                ),
            ),
            source=fragment.nodes[0].source,
        )
        for fact in combined
    )
    _require_distinct_branches(label, combined, rows)

    rule = DecisionRule(
        id=ids.SUPPLY_VERIFIED_BARRIER_TRANSFER,
        inputs=(
            DecisionInput(name="galvanic_isolation_verified", kind="boolean"),
            DecisionInput(
                name="isolation_evidence_kind",
                kind="categorical",
                allowed_values=_ISOLATION_EVIDENCE_KINDS,
            ),
            DecisionInput(
                name="downstream_connection_kind",
                kind="categorical",
                allowed_values=_DOWNSTREAM_CONNECTION_KINDS,
            ),
        ),
        outputs=(
            DecisionOutput(name="transfer_permitted", kind="boolean"),
            DecisionOutput(
                name="combined_circuit_requirement",
                kind="categorical",
                allowed_values=requirements,
            ),
            DecisionOutput(name="propagates_to_connected_circuits", kind="boolean"),
        ),
        rows=rows,
        exhaustive=False,
        source=fragment.source,
    )
    return (rule,), (_proposal(rule, "decision", fragment),)


# --- transient limiter (SPD) reduction requirements --------------------------------

#: The consumer's question space for placement. ``bundled_external_to_pecs`` is its own question
#: because the monitoring clause's external-device requirement reaches only a device the
#: manufacturer bundles with their product: a consumer asking about any other external device gets
#: no match, which is what the source states about it -- nothing.
_DEVICE_PLACEMENTS = ("internal_to_pecs", "external_to_pecs", "bundled_external_to_pecs")

#: DVC designations. Designations only; no source value or wording. The document defines
#: exactly these three (3.19, 3.20, 3.21) and Table 2 and Table 3 name no others; there is
#: no DVC A and no DVC D. Table 2 splits DVC As into a wet and a dry row, which changes the
#: voltage limits, not the designation.
#:
#: Declared here beside the other consumer question spaces rather than in the attenuation section,
#: because the reviewed-versus-consumer table below reads it: the gate is a reviewed scope now, and
#: leaving it out of that table is the drift the table exists to refuse.
_DVC_DESIGNATIONS = ("dvc_as", "dvc_b", "dvc_c")

#: The consumer's question space for the insulation class. Declared above the reviewed-versus-consumer
#: table below, because that table reads it.
_INSULATION_CLASSES = ("functional", "basic", "supplementary", "double", "reinforced")

#: The consumer's question space for evidence, declared here and never derived from the reviewed
#: facts. ``none`` -- no evidence yet -- is the first question a consumer asks and no authored
#: statement can name it, so deriving this vocabulary from the facts would put that question
#: outside the input's allowed values and raise instead of answering it.
#:
#: Declared here beside the other consumer question spaces rather than in the attenuation section,
#: for the reason ``_DVC_DESIGNATIONS`` is: the reviewed-versus-consumer table below reads it now
#: that the evidence reading is a scope.
_ATTENUATION_EVIDENCE_KINDS = ("none", "test", "simulation", "calculation")

#: Per reviewed dimension: the fact field's declared domain, and the consumer input it projects
#: into. Keyed by fact field name, since two of the inputs are named differently from the field
#: that feeds them. Where the two domains coincide an unrestricted reading is a wildcard; where the
#: reviewed domain is narrower it is an explicit ``in``, because the difference is exactly the set
#: of consumer states no reviewed reading can name.
_REVIEWED_AND_CONSUMER_DOMAINS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    #: Not projected through ``_scope_matcher`` -- the route settles this one, so a statement names
    #: one concrete kind and the row is a plain equality. Declared here anyway, because the
    #: import-time check below is what refuses a reviewed value the input never declares.
    "supply_kind": (_reviewed_domain(SystemVoltageMeasureFact, "supply_kind"), _SUPPLY_KINDS),
    "phase_system": (
        _reviewed_domain(SystemVoltageMeasureFact, "phase_system"),
        _PHASE_SYSTEMS,
    ),
    "earthing": (
        _reviewed_domain(SystemVoltageMeasureFact, "earthing"),
        _EARTHING_ARRANGEMENTS,
    ),
    "input_topology": (
        _reviewed_domain(SystemVoltageMeasureFact, "input_topology"),
        _INPUT_TOPOLOGIES,
    ),
    "purpose": (
        _reviewed_domain(SystemVoltageMeasureFact, "purpose"),
        _CALCULATION_PURPOSES,
    ),
    "device_placement": (
        _reviewed_domain(SpdMonitoringRequirementFact, "device_placement"),
        _DEVICE_PLACEMENTS,
    ),
    #: The reviewed domain is the three routes a statement can accept; the consumer's also carries
    #: the absence of evidence, which no reviewed reading may answer for. That gap is why an
    #: unrestricted evidence reading projects an ``in`` rather than a wildcard, which
    #: ``_evidence_matcher`` used to arrange by hand.
    "evidence_kind": (
        _reviewed_domain(HfAttenuationRequirementFact, "evidence_kind"),
        _ATTENUATION_EVIDENCE_KINDS,
    ),
    #: The reviewed and consumer domains coincide here, so an unrestricted class reading is a
    #: wildcard. It is in the table anyway: leaving a projected scope out of it is exactly the drift
    #: the table exists to refuse, and a class the reviewed vocabulary later narrows would otherwise
    #: keep over-matching silently.
    "insulation_classes": (
        _reviewed_domain(SpdReductionPermissionFact, "insulation_classes"),
        _INSULATION_CLASSES,
    ),
    "dvc_gate": (_reviewed_domain(HfAttenuationPermissionFact, "dvc_gate"), _DVC_DESIGNATIONS),
}


def _require_reviewed_domains_within_consumer_domains() -> None:
    """Refuse, at import, a reviewed domain carrying a value its consumer input never declares.

    The reverse of the over-match: a reviewed value outside the consumer's ``allowed_values`` makes
    ``DecisionRule`` refuse the whole row at construction, which is a build failure whose message is
    about matchers rather than about authoring.
    """

    for dimension, (reviewed, consumer) in _REVIEWED_AND_CONSUMER_DOMAINS.items():
        outside = sorted(set(reviewed) - set(consumer))
        if outside:
            raise ValueError(f"{dimension} reviewed domain declares {outside} outside its input")


_require_reviewed_domains_within_consumer_domains()
_VERIFICATION_REFERENCES = ("inspection_and_dielectric_verification", "not_required")

#: The monitoring route's own clause states no category step at all (``SpdMonitoringFact``
#: carries no OVC field), so its rows fill this shared output with this one fixed token
#: rather than a value borrowed from the mains/non-mains routes' vocabulary.
_NOT_REDUCED = "not_reduced"


def _spd_permission_row(
    fact: SpdReductionPermissionFact,
    step: OvercategoryStep,
    fragment: RawClauseFragment,
) -> DecisionRow:
    """One row for one permitted transition of one reviewed permission statement.

    **One row per step, not per statement**, and that is the one place a collection legitimately
    expands. A scope is one condition over several values with one answer, so it stays one row; a
    step collection is a mapping, each pair carrying its own reduced category, so the rows differ in
    both their matched source category and their answer. Projecting one row and picking a target
    would be choosing one of the reviewed pairs arbitrarily, and projecting one row per step without
    matching the source category would leave every row but the first shadowed.

    ``reduction_permitted`` is not independently authored content: a permission statement is what
    grants it, so it mirrors the statement's presence -- the same way a verified barrier's transfer
    permission mirrors its own scope. Where no reviewed permission covers a query the rule is
    non-exhaustive and the query reaches no row, rather than being told a reduction is not permitted
    by a statement that never addressed it.
    """

    reviewed_classes, consumer_classes = _REVIEWED_AND_CONSUMER_DOMAINS["insulation_classes"]
    return DecisionRow(
        matchers=(
            _matcher("source_overvoltage_category", (step.source_ovc,)),
            _scope_matcher(
                "insulation_class", fact.insulation_classes, reviewed_classes, consumer_classes
            ),
            Matcher(input="part_of_category_reduction", op="equals", boolean=True),
        ),
        values=(
            DecisionValue(name="reduction_permitted", boolean=True),
            DecisionValue(name="reduced_category", categorical=step.target_ovc),
        ),
        source=_statement_source(fact, (fragment,)),
    )


def _spd_device_monitoring_row(
    fact: SpdReductionMonitoringFact, fragment: RawClauseFragment
) -> DecisionRow:
    """One row for one reviewed statement of the monitoring a reducing device owes.

    Its own rule's row rather than more values on the permission's: the statement scopes the device's
    degradability and nothing the permission scopes, and the permission scopes the category and the
    insulation class and nothing this one scopes. Sharing one row shape meant each had to match the
    other's dimensions with a wildcard, which made the two rows overlap on every degradable device
    inside a reduction -- so ``_require_distinct_branches`` refused the pair and neither reading could
    be projected beside the other.

    ``monitoring_reference`` is emitted as a reference rather than resolved: the obligation is
    specified by a separately reviewed route, and following it is the consumer's step, not this
    projection's.
    """

    return DecisionRow(
        matchers=(Matcher(input="device_degradable", op="equals", boolean=fact.device_degradable),),
        values=(
            DecisionValue(
                name="monitoring_required", boolean=fact.monitoring_obligation == "required"
            ),
            DecisionValue(
                name="status_indication_required", boolean=fact.status_indication == "required"
            ),
            DecisionValue(name="monitoring_reference", reference=fact.monitoring_reference),
        ),
        source=_statement_source(fact, (fragment,)),
    )


def _spd_monitoring_row(
    fact: SpdMonitoringRequirementFact | SpdMonitoringExemptionFact,
    fragment: RawClauseFragment,
) -> DecisionRow:
    """One row for one reviewed monitoring requirement or exemption.

    Whether monitoring is owed is *what the variant is*, not a value read off a field: a
    requirement projects the obligation and an exemption projects its absence. A boolean beside the
    variant could contradict it, and the pair of readings would then depend on which of the two
    the projector believed.

    ``device_placement`` is a branch dimension of a requirement and a dimension an exemption does
    not state. An exemption therefore projects the unrestricted reading -- an ``in`` over the
    reviewed placements, never a wildcard -- so it covers every placement a reviewed statement can
    name and stops there: this rule declares a bare external placement the reviewed vocabulary
    deliberately cannot name, because what the source states about it is nothing, and a wildcard
    would grant it a row anyway.

    ``participates_in_reduction`` is the dimension that separates the two kinds, which is why a
    requirement states it as well. Without it a requirement would overlap every exemption and
    ``_require_distinct_branches`` would refuse the pair rather than serve whichever came first.

    The three reduction outputs below are the mains and non-mains routes' concern; this route
    fills them with a fixed, uninformative value only because all three routes still share one
    declared output tuple. Right-sizing that per route is #53C item 5.
    """

    requirement = fact if isinstance(fact, SpdMonitoringRequirementFact) else None
    required = requirement is not None
    reviewed, consumer = _REVIEWED_AND_CONSUMER_DOMAINS["device_placement"]
    placement: DimensionScope[Any] = (
        requirement.device_placement
        if requirement is not None
        else DimensionScope[str].unrestricted()
    )
    return DecisionRow(
        matchers=(
            _scope_matcher("device_placement", placement, reviewed, consumer),
            Matcher(input="insulation_class", op="any"),
            Matcher(input="device_degradable", op="any"),
            Matcher(
                input="part_of_category_reduction",
                op="equals",
                boolean=fact.participates_in_reduction,
            ),
        ),
        values=(
            DecisionValue(name="reduction_permitted", boolean=False),
            DecisionValue(name="reduced_category", categorical=_NOT_REDUCED),
            DecisionValue(name="monitoring_required", boolean=required),
            DecisionValue(name="status_indication_required", boolean=required),
            DecisionValue(
                name="verification_reference",
                categorical=(
                    "inspection_and_dielectric_verification" if required else "not_required"
                ),
            ),
            DecisionValue(name="reinforced_floor_applies", boolean=False),
        ),
        source=fragment.nodes[0].source,
    )


def project_spd_reduction_requirements(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    confirmed_facts: ConfirmedFacts = _NO_CONFIRMED_FACTS,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project the transient-limiter monitoring and reduction clauses into decisions.

    Registered for all three SPD routes (mains, non_mains, monitoring) under one function body: the
    fragment passed to a given call is that route's own fragment, and its id says which route this
    call produces. Every route refuses to project without its own family's facts.

    The monitoring clause's route projects one rule from its own ``spd_monitoring`` statements. Each
    reduction route projects **two**, because its clause states two normatively different executable
    readings that scope different dimensions: the permission over a category transition and an
    insulation class, and the monitoring a degradable reducing device owes. Held in one rule they had
    to match each other's dimensions with a wildcard, so their rows overlapped on every degradable
    device inside a reduction and ``_require_distinct_branches`` refused the pair -- the merged
    ``SpdReductionFact`` hid that only by recording all of it as one statement. Two rules, each with
    exactly the inputs its own statements scope and the outputs they state, is the contract that
    lets all of the clause's readings project at once.

    The reduction family's **floor** statements are carried, not projected. A floor is a comparison
    against a basis, and both the comparison and a route that evaluates it are #53C's; the statement
    is resolved and covered by the route's fact-set digest and reaches no row. A consumer asking
    about an insulation class only a floor statement names therefore reaches no row at all, rather
    than an answer no reviewed permission supports.
    """

    label = "supply SPD reduction requirements"
    rule_id = fragment.id.removeprefix("raw-")
    shape = _SPD_SHAPE_BY_ROUTE.get(rule_id)
    if shape is None:
        raise ValueError(f"{label} projection requires its own fragment")
    _require_own_fragment(fragment, identity, rule_id, label)
    _require_shape(fragment, shape, label)

    facts = confirmed_facts.for_route(rule_id)
    if not facts:
        raise ClauseStructureError(f"{label} needs reviewed clause facts for its route")

    rules: tuple[DecisionRule, ...] = (
        (_spd_monitoring_rule(label, rule_id, fragment, facts),)
        if rule_id == _SPD_MONITORING_ROUTE
        else _spd_reduction_rules(label, rule_id, fragment, facts)
    )
    return rules, tuple(_proposal(rule, "decision", fragment) for rule in rules)


def _spd_monitoring_rule(
    label: str,
    rule_id: str,
    fragment: RawClauseFragment,
    facts: tuple[SupplyFact, ...],
) -> DecisionRule:
    """The SPD placement monitoring clause's own decision, from its own reviewed statements.

    Its declared shape is unchanged: right-sizing this route's own outputs, which still carry the
    reduction routes' three and fill them with a fixed uninformative value, stays #53C item 5.
    """

    monitoring_facts = tuple(fact for fact in facts if isinstance(fact, SpdMonitoringStatement))
    if len(monitoring_facts) != len(facts):
        raise ValueError(f"{label} projection requires SPD monitoring facts")
    # The family's **compliance** statements are carried, not projected: they state how a showing is
    # accepted, which none of this rule's declared outputs can carry. A reviewed set of only those
    # cannot answer the question this rule asks, so the projection refuses rather than emitting a
    # rule with no rows -- a zero-row rule answers every consumer with silence and looks reviewed
    # while doing it.
    obligations = tuple(
        fact
        for fact in monitoring_facts
        if isinstance(fact, SpdMonitoringRequirementFact | SpdMonitoringExemptionFact)
    )
    if not obligations:
        raise ClauseStructureError(
            f"{label} reviewed statements state no monitoring obligation, so they cannot "
            "answer its question"
        )
    rows = tuple(_spd_monitoring_row(fact, fragment) for fact in obligations)
    _require_distinct_branches(label, obligations, rows)
    return DecisionRule(
        id=rule_id,
        inputs=(
            DecisionInput(
                name="device_placement", kind="categorical", allowed_values=_DEVICE_PLACEMENTS
            ),
            DecisionInput(
                name="insulation_class",
                kind="categorical",
                allowed_values=_INSULATION_CLASSES,
            ),
            DecisionInput(name="device_degradable", kind="boolean"),
            DecisionInput(name="part_of_category_reduction", kind="boolean"),
        ),
        outputs=(
            DecisionOutput(name="reduction_permitted", kind="boolean"),
            DecisionOutput(
                name="reduced_category",
                kind="categorical",
                allowed_values=(_NOT_REDUCED,),
            ),
            DecisionOutput(name="monitoring_required", kind="boolean"),
            DecisionOutput(name="status_indication_required", kind="boolean"),
            DecisionOutput(
                name="verification_reference",
                kind="categorical",
                allowed_values=_VERIFICATION_REFERENCES,
            ),
            DecisionOutput(name="reinforced_floor_applies", kind="boolean"),
        ),
        rows=rows,
        exhaustive=False,
        source=fragment.source,
    )


def _spd_reduction_rules(
    label: str,
    rule_id: str,
    fragment: RawClauseFragment,
    facts: tuple[SupplyFact, ...],
) -> tuple[DecisionRule, ...]:
    """One reduction route's two decisions: the permission, and the reducing device's monitoring."""

    reduction_facts = tuple(fact for fact in facts if isinstance(fact, SpdReductionStatement))
    if len(reduction_facts) != len(facts):
        raise ValueError(f"{label} projection requires SPD reduction facts")
    permissions = tuple(
        fact for fact in reduction_facts if isinstance(fact, SpdReductionPermissionFact)
    )
    if not permissions:
        raise ClauseStructureError(
            f"{label} reviewed statements permit no category reduction, so they cannot "
            "answer its question"
        )
    # One row per permitted transition, and the statement repeated alongside each so a collision
    # names the statement it came from rather than a row index nobody authored.
    stepped = tuple((fact, step) for fact in permissions for step in fact.permitted_steps)
    permission_rows = tuple(_spd_permission_row(fact, step, fragment) for fact, step in stepped)
    _require_distinct_branches(label, tuple(fact for fact, _step in stepped), permission_rows)
    permission = DecisionRule(
        id=rule_id,
        inputs=(
            DecisionInput(
                name="source_overvoltage_category",
                kind="categorical",
                allowed_values=_OVERVOLTAGE_CATEGORIES,
            ),
            DecisionInput(
                name="insulation_class",
                kind="categorical",
                allowed_values=_INSULATION_CLASSES,
            ),
            DecisionInput(name="part_of_category_reduction", kind="boolean"),
        ),
        outputs=(
            DecisionOutput(name="reduction_permitted", kind="boolean"),
            DecisionOutput(
                name="reduced_category",
                kind="categorical",
                allowed_values=tuple(dict.fromkeys(step.target_ovc for _fact, step in stepped)),
            ),
        ),
        rows=permission_rows,
        exhaustive=False,
        source=fragment.source,
    )

    monitoring_facts = tuple(
        fact for fact in reduction_facts if isinstance(fact, SpdReductionMonitoringFact)
    )
    if not monitoring_facts:
        return (permission,)
    monitoring_rows = tuple(_spd_device_monitoring_row(fact, fragment) for fact in monitoring_facts)
    _require_distinct_branches(label, monitoring_facts, monitoring_rows)
    device_monitoring = DecisionRule(
        id=f"{rule_id}.{_SPD_DEVICE_MONITORING_SUFFIX}",
        inputs=(DecisionInput(name="device_degradable", kind="boolean"),),
        outputs=(
            DecisionOutput(name="monitoring_required", kind="boolean"),
            DecisionOutput(name="status_indication_required", kind="boolean"),
            DecisionOutput(name="monitoring_reference", kind="reference"),
        ),
        rows=monitoring_rows,
        exhaustive=False,
        source=fragment.source,
    )
    return (permission, device_monitoring)


# --- high-frequency isolating transformer ------------------------------------------

#: What a consumer must still show, never an echo of what it supplied.
_REQUIRED_EVIDENCE_KINDS = ("test_or_simulation_or_calculation", "already_provided")
#: Multipliers from a reviewed frequency unit token to hertz. Names the units the
#: generic tokenizer emits; the threshold itself is read from the document.
_FREQUENCY_UNIT_SCALES = {"Hz": 1, "kHz": 1_000, "MHz": 1_000_000}


def _frequency_threshold_hz(fragment: RawClauseFragment, label: str) -> Decimal:
    """Read the clause's single frequency threshold from its reviewed tokens."""

    pairs = [
        (token, fragment.tokens[index + 1])
        for index, token in enumerate(fragment.tokens)
        if token.kind == "quantity"
        and index + 1 < len(fragment.tokens)
        and fragment.tokens[index + 1].kind == "unit"
        and str(fragment.tokens[index + 1].normalized) in _FREQUENCY_UNIT_SCALES
    ]
    if len(pairs) != 1:
        _fail(f"{label} expected exactly one reviewed frequency quantity and unit pair")
    quantity, unit = pairs[0]
    return Decimal(quantity.normalized) * _FREQUENCY_UNIT_SCALES[str(unit.normalized)]


def project_hf_transformer_attenuation(
    fragment: RawClauseFragment,
    identity: StandardIdentity,
    _draft: object = None,
    confirmed_facts: ConfirmedFacts = _NO_CONFIRMED_FACTS,
) -> tuple[tuple[DecisionRule, ...], tuple[SemanticProposal, ...]]:
    """Project the isolating-transformer attenuation clause into a decision.

    **Both of the clause's readings are projected, and neither alone is the rule.** The permission
    states the gate the working-voltage basis applies under; the demonstration requirement states
    the evidence routes the transformer's ability may be shown by. This rule declares an input and
    an output for each half, so each row's matchers and values trace to the statement that states
    them, and the composition is the clause's -- which is what a clause projector is for. Reading
    both halves off one flat fact was what forced the permission to carry an evidence route it never
    states, and it is what the ``statement_kind`` split ends.

    - The **shown** rows are one per reviewed permission: its own gate scope, against the evidence
      routes the requirement statements accept. A scope is one condition with one answer, so a
      permission naming both designations is one row, and the accepted routes are one ``in`` rather
      than a row per route.
    - The **outstanding** rows are one per concrete designation the permissions gate, and they exist
      because a requirement was reviewed: the route is an engineering-input requirement until the
      attenuation is shown, never a permission. One per designation rather than per statement,
      because several permissions may gate one designation and the showing is outstanding for it
      once. They come first, so no consumer reaches a permission by supplying no evidence -- and the
      shown rows' evidence matcher is an ``in`` over the reviewed routes rather than a wildcard, so
      the absence of a showing reaches no permission from that side either.

    ``working_voltage_basis_permitted`` is not independently authored content: a permission statement
    is what grants it, so it mirrors that statement's presence, the same way a verified barrier's
    transfer permission mirrors its own in ``project_verified_barrier_transfer``.

    A route missing **either** reading refuses rather than projecting half a clause: without a
    permission there is no gate and nothing granted, and without a requirement there is no accepted
    showing to condition the grant on -- projecting the permission alone would grant the basis to a
    circuit that has shown nothing.

    The frequency threshold stays read from the fragment's own tokens rather than declared: it is
    a numeric source value, and an existing test pins that behaviour.
    """

    label = "supply high-frequency transformer attenuation"
    _require_own_fragment(fragment, identity, ids.SUPPLY_HF_TRANSFORMER_ATTENUATION, label)
    _require_shape(fragment, _HF_TRANSFORMER_SHAPE, label)
    threshold_hz = _frequency_threshold_hz(fragment, label)

    facts = confirmed_facts.for_route(ids.SUPPLY_HF_TRANSFORMER_ATTENUATION)
    if not facts:
        raise ClauseStructureError(f"{label} needs reviewed clause facts for its route")
    permissions = tuple(fact for fact in facts if isinstance(fact, HfAttenuationPermissionFact))
    requirements = tuple(fact for fact in facts if isinstance(fact, HfAttenuationRequirementFact))
    if len(permissions) + len(requirements) != len(facts):
        raise ValueError(f"{label} projection requires HF attenuation facts")
    if not permissions:
        raise ClauseStructureError(f"{label} needs a reviewed permission statement for its route")
    if not requirements:
        raise ClauseStructureError(f"{label} needs a reviewed demonstration requirement statement")

    reviewed_gates, consumer_gates = _REVIEWED_AND_CONSUMER_DOMAINS["dvc_gate"]
    reviewed_evidence, _consumer_evidence = _REVIEWED_AND_CONSUMER_DOMAINS["evidence_kind"]
    # The showings this clause's requirement accepts, in the reviewed domain's declared order. The
    # union across the requirement statements, because each states which showings suffice and a
    # second statement widens that rather than narrowing it -- and a statement restricting the
    # routes to nothing accepts every reviewed one, never the absence of a showing.
    accepted_evidence = tuple(
        kind
        for kind in reviewed_evidence
        if any(
            not fact.evidence_kind.values or kind in fact.evidence_kind.values
            for fact in requirements
        )
    )

    def _row(*, gate: Matcher, evidence: Matcher, permitted: bool, required: str) -> DecisionRow:
        return DecisionRow(
            matchers=(
                gate,
                Matcher(input="transformer_frequency_hz", op="range", minimum=threshold_hz),
                Matcher(input="isolation_provided", op="equals", boolean=True),
                evidence,
            ),
            values=(
                DecisionValue(name="working_voltage_basis_permitted", boolean=permitted),
                DecisionValue(name="required_evidence_kinds", categorical=required),
            ),
            source=fragment.nodes[0].source,
        )

    # One outstanding-showing row per concrete designation the permissions gate rather than per
    # statement: several permissions may cover one designation, and the showing is outstanding for
    # that designation once. A permission whose gate restricts nothing leaves it outstanding for
    # every designation its own reviewed domain names -- never for a designation outside it.
    outstanding = tuple(
        _row(
            gate=_matcher("circuit_dvc", (designation,)),
            evidence=_matcher("attenuation_evidence_kind", ("none",)),
            permitted=False,
            required="test_or_simulation_or_calculation",
        )
        for designation in dict.fromkeys(
            designation
            for fact in permissions
            for designation in (fact.dvc_gate.values or reviewed_gates)
        )
    )
    shown = tuple(
        _row(
            gate=_scope_matcher("circuit_dvc", fact.dvc_gate, reviewed_gates, consumer_gates),
            evidence=_matcher("attenuation_evidence_kind", accepted_evidence),
            permitted=True,
            required="already_provided",
        )
        for fact in permissions
    )
    # Over the per-permission rows only: the outstanding-showing rows are one per distinct gate
    # and so distinct by construction, and they carry no statement to name in a refusal.
    _require_distinct_branches(label, permissions, shown)

    rule = DecisionRule(
        id=ids.SUPPLY_HF_TRANSFORMER_ATTENUATION,
        inputs=(
            DecisionInput(name="circuit_dvc", kind="categorical", allowed_values=_DVC_DESIGNATIONS),
            DecisionInput(name="transformer_frequency_hz", kind="numeric", unit="Hz"),
            DecisionInput(name="isolation_provided", kind="boolean"),
            DecisionInput(
                name="attenuation_evidence_kind",
                kind="categorical",
                allowed_values=_ATTENUATION_EVIDENCE_KINDS,
            ),
        ),
        outputs=(
            DecisionOutput(name="working_voltage_basis_permitted", kind="boolean"),
            DecisionOutput(
                name="required_evidence_kinds",
                kind="categorical",
                allowed_values=_REQUIRED_EVIDENCE_KINDS,
            ),
        ),
        rows=outstanding + shown,
        exhaustive=False,
        source=fragment.source,
    )
    return (rule,), (_proposal(rule, "decision", fragment),)


CLAUSE_PROJECTORS = {
    ids.SUPPLY_SYSTEM_VOLTAGE_RESOLUTION: project_system_voltage_resolution,
    ids.SUPPLY_MULTIPLE_SOURCE_PROPAGATION: project_multiple_source_propagation,
    ids.SUPPLY_VERIFIED_BARRIER_TRANSFER: project_verified_barrier_transfer,
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.mains": project_spd_reduction_requirements,
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.non_mains": project_spd_reduction_requirements,
    f"{ids.SUPPLY_SPD_REDUCTION_REQUIREMENTS}.monitoring": project_spd_reduction_requirements,
    ids.SUPPLY_HF_TRANSFORMER_ATTENUATION: project_hf_transformer_attenuation,
}

__all__ = [
    "CLAUSE_PROJECTORS",
    "LEGACY_BRANCH_AUTHORITY_RULE_IDS",
    "SUPPLY_CLAUSES",
    "SUPPLY_FACT_FAMILY_BY_ROUTE",
    "SUPPLY_FACT_GRAMMAR_FILE",
    "SUPPLY_FACT_ISOLATION_BY_ROUTE",
    "SUPPLY_FACT_SUPPLY_KIND_BY_ROUTE",
    "SUPPLY_SYSTEM_VOLTAGE_NON_MAINS",
    "declared_rule_references",
    "project_hf_transformer_attenuation",
    "project_multiple_source_propagation",
    "project_spd_reduction_requirements",
    "project_system_voltage_resolution",
    "project_verified_barrier_transfer",
    "propose_supply_facts",
    "supply_fact_proposal_grammars",
]
