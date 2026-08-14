"""Deterministic sentence-level drafts of a route's clause facts, computed on demand.

A proposal is a prefill of the authoring editor, never a reading of the source and never a
review: it is derived from the private fragment plus the recipe's declared rules every time
it is asked for, and nothing here is stored on the draft. A clause fact review binds its
evidence and the fact's own hash rather than a proposal digest, so a re-extraction simply
re-proposes and re-opens nothing.

The division mirrors the one ``AxisKeywordRule`` and ``AxisSelectorSpec`` already keep for a
grid axis: the rule *types* are generic and live here, while which keyword settles which
dimension is declared in the recipe beside the clause specs. No clause prose, no statement
inventory and no sentence-to-statement mapping belongs in this repository -- only the neutral
vocabulary each dimension draws from and the short generic terms a sentence is scanned for.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import Any, Literal, get_args

from pydantic import Field, model_validator

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import Identifier, RulePackageError
from insulation_coordination.rules.importer.clause_facts import (
    BarrierCombinedRequirementFact,
    BarrierDownstreamInheritanceFact,
    BarrierRatingResolutionFact,
    CitedNode,
    DimensionScope,
    HfAttenuationFact,
    OvercategoryStep,
    PropagationStepFact,
    SpdMonitoringComplianceFact,
    SpdMonitoringExemptionFact,
    SpdMonitoringRequirementFact,
    SpdReductionFloorFact,
    SpdReductionMonitoringFact,
    SpdReductionPermissionFact,
    SupplyFact,
    SystemVoltageApplicabilityFact,
    SystemVoltageMeasureFact,
    pair_vocabulary,
    scope_vocabulary,
)
from insulation_coordination.rules.importer.clauses import RawClauseFragment
from insulation_coordination.rules.importer.extract import canonical_model_sha256

FactModel = type[
    SystemVoltageMeasureFact
    | SystemVoltageApplicabilityFact
    | PropagationStepFact
    | BarrierRatingResolutionFact
    | BarrierCombinedRequirementFact
    | BarrierDownstreamInheritanceFact
    | SpdReductionPermissionFact
    | SpdReductionFloorFact
    | SpdReductionMonitoringFact
    | SpdMonitoringRequirementFact
    | SpdMonitoringExemptionFact
    | SpdMonitoringComplianceFact
    | HfAttenuationFact
]

#: Every statement variant each declared fact family builds, in declaration order. The single
#: source the editor, the proposer and the recipe's own family checks all read, so a family added
#: to one of them and forgotten in another cannot happen.
#:
#: A tuple per family rather than one model, because a family whose clause states normatively
#: different *kinds* of reading has no single model whose fields answer for all of it -- amendment
#: A3-C. A one-kind family is a one-member tuple and its callers pass no statement kind at all.
FACT_MODELS_BY_KIND: dict[str, tuple[FactModel, ...]] = {
    "system_voltage": (SystemVoltageMeasureFact, SystemVoltageApplicabilityFact),
    "propagation_step": (PropagationStepFact,),
    "barrier_transfer": (
        BarrierRatingResolutionFact,
        BarrierCombinedRequirementFact,
        BarrierDownstreamInheritanceFact,
    ),
    "spd_reduction": (
        SpdReductionPermissionFact,
        SpdReductionFloorFact,
        SpdReductionMonitoringFact,
    ),
    "spd_monitoring": (
        SpdMonitoringRequirementFact,
        SpdMonitoringExemptionFact,
        SpdMonitoringComplianceFact,
    ),
    "hf_attenuation": (HfAttenuationFact,),
}

#: ``fact_kind`` is the family itself, fixed per route; ``statement_kind`` is which variant of it,
#: chosen before the dimensions are shown at all; ``statement_index`` has its own spinner;
#: ``node_references`` come from the node reader, never typed by hand.
_UNDIMENSIONED_FIELDS = frozenset(
    {"fact_kind", "statement_kind", "statement_index", "node_references"}
)

DimensionKind = Literal["choice", "boolean", "identifier", "scope", "pair_sequence"]

#: A boolean dimension's two authored values. Spelled as text because that is what an editor
#: offers and what a declared rule states; converted once, in ``proposed_fact``.
_BOOLEAN_VALUES = ("true", "false")

#: A scope dimension's wire value on a proposal: this token for the unrestricted reading, otherwise
#: the canonically ordered tokens joined by ``|``. ``ClauseFactProposal.chosen`` stays
#: ``dict[str, str]`` because it is a prefill of an editor, not a stored reading -- an absent key
#: still means unchosen, and a typed payload here would model a wire form the grammar relocation is
#: about to move anyway.
#:
#: ponytail: a string encoding rather than a payload model. One encode point (``scope_wire``) and
#: one decode point (``scope_from_wire``); upgrade to a typed payload when the private grammar
#: needs to propose anything a string cannot carry.
SCOPE_UNRESTRICTED = "*"
_SCOPE_SEPARATOR = "|"

#: A pair collection's wire value: each pair's two members joined by this arrow, the pairs
#: themselves separated like a scope's values. One reading carries every pair it names, never one
#: draft per pair -- the same duplicate-expansion fix ``exact_set`` made for a scope.
_PAIR_ARROW = ">"

#: The member names a decoded pair fills, read from the one pair model this repository declares.
#:
#: ponytail: one shared member order rather than threading the field name through every decode site.
#: Read from the model so it cannot drift from it; give ``authored_dimension`` the field name when a
#: second pair collection with different members arrives.
_PAIR_MEMBER_FIELDS: tuple[str, ...] = tuple(OvercategoryStep.model_fields)

#: The longest a declared keyword may be. Keywords are short generic engineering terms; this cap
#: is what stops a whole clause sentence from being pasted into a public file as a "keyword".
_MAX_KEYWORD_WORDS = 4
_MAX_KEYWORD_LENGTH = 40


def fact_variants(fact_kind: str) -> tuple[str, ...]:
    """Each statement kind one family declares, in declaration order.

    Empty for a family that states one kind of reading: such a family has no variant to choose, and
    an empty tuple is what lets every caller ask without special-casing the families that have none.
    """

    models = FACT_MODELS_BY_KIND[fact_kind]
    if len(models) == 1:
        return ()
    return tuple(
        str(get_args(model.model_fields["statement_kind"].annotation)[0]) for model in models
    )


def fact_model(fact_kind: str, statement_kind: str | None = None) -> FactModel:
    """The one model a family's statement kind builds.

    ``statement_kind`` is required exactly when the family declares variants, and refused when it
    does not: a caller that guesses a variant would author a reading of a kind nobody chose, and a
    caller that omits one for a family that has them would silently get whichever variant happens to
    be declared first.
    """

    models = FACT_MODELS_BY_KIND[fact_kind]
    variants = fact_variants(fact_kind)
    if not variants:
        if statement_kind is not None:
            raise RulePackageError(f"{fact_kind} declares one statement kind, not {statement_kind}")
        return models[0]
    if statement_kind not in variants:
        raise RulePackageError(f"{fact_kind} states {list(variants)}, not {statement_kind}")
    return models[variants.index(statement_kind)]


def fact_dimensions(
    fact_kind: str, statement_kind: str | None = None
) -> tuple[tuple[str, DimensionKind, tuple[str, ...]], ...]:
    """Each authored dimension of one statement kind with its widget kind and vocabulary.

    Read from the model's own annotations, so neither the editor nor a declared rule carries a
    hand-written copy of a vocabulary that could drift from the model it has to build. A boolean
    is a two-value choice starting unchosen -- a reviewer must never record a reading they did
    not pick, and a checkbox has no unchosen state. A ``DimensionScope`` field is a ``"scope"``
    over the same kind of vocabulary, offered as a multi-selection plus an explicit unrestricted
    entry rather than as one value. An ordered collection of pairs is a ``"pair_sequence"`` over the
    vocabulary both halves draw from. An ``Identifier`` field has no vocabulary and gets a line edit.
    Anything else is refused here rather than degrading silently: a dimension the editor cannot
    offer is a fact no reviewer can author, and approval would block on the route with nothing to
    explain why.
    """

    dimensions: list[tuple[str, DimensionKind, tuple[str, ...]]] = []
    for name, field in fact_model(fact_kind, statement_kind).model_fields.items():
        if name in _UNDIMENSIONED_FIELDS:
            continue
        if field.annotation is bool:
            dimensions.append((name, "boolean", _BOOLEAN_VALUES))
            continue
        scoped = scope_vocabulary(field.annotation)
        if scoped:
            dimensions.append((name, "scope", scoped))
            continue
        paired = pair_vocabulary(field.annotation)
        if paired:
            dimensions.append((name, "pair_sequence", paired))
            continue
        options = get_args(field.annotation)
        if options:
            if not all(isinstance(option, str) for option in options):
                raise RulePackageError(
                    f"{fact_kind}.{name} declares no vocabulary of strings the review "
                    "dialog could offer"
                )
            dimensions.append((name, "choice", options))
            continue
        if field.annotation is str:
            dimensions.append((name, "identifier", ()))
            continue
        raise RulePackageError(
            f"{fact_kind}.{name} declares no vocabulary of strings the review dialog could offer"
        )
    return tuple(dimensions)


def scope_wire(scope: DimensionScope[Any]) -> str:
    """One reviewed scope as a proposal's wire value, and as a compact display of the reading.

    The values are already canonical, so this neither sorts nor deduplicates: two statements
    naming one set encode identically because the model made them identical.

    ``DimensionScope[Any]`` because every family parametrizes the scope with its own vocabulary and
    the parametrizations are invariant: this reads ``mode`` and ``values`` and needs neither.
    """

    return (
        SCOPE_UNRESTRICTED if scope.mode == "unrestricted" else _SCOPE_SEPARATOR.join(scope.values)
    )


def scope_tokens(value: str) -> tuple[str, ...]:
    """The tokens one scope wire value names; empty for the unrestricted reading."""

    return () if value == SCOPE_UNRESTRICTED else tuple(value.split(_SCOPE_SEPARATOR))


def scope_from_wire(value: str) -> dict[str, object]:
    """One scope dimension's authored value, decoded from its wire form.

    Dumped rather than returned as a model: the wire form carries no vocabulary, so the reading is
    validated against the fact field's own parametrized scope when the statement is built, which is
    what refuses a token that family never declared.
    """

    tokens = scope_tokens(value)
    scope = DimensionScope[str].unrestricted() if not tokens else DimensionScope[str].of(*tokens)
    return scope.model_dump()


def pair_wire(pairs: Sequence[Sequence[str]]) -> str:
    """One ordered pair collection as a wire value, and as a compact display of the reading.

    Neither sorted nor deduplicated here: the fact model's own validator refuses a collection out of
    declared order or naming one pair twice, and quietly fixing it up on the way in would hide the
    duplicate a reviewer meant to notice.
    """

    return _SCOPE_SEPARATOR.join(_PAIR_ARROW.join(members) for members in pairs)


def authored_pair_wire(members: Sequence[object]) -> str:
    """One authored pair collection's wire value, read off the member models themselves.

    The inverse of ``pair_from_wire``, and the one place a stored collection is spelled the way an
    editor and a proposal spell it, so a row summary and the editor cannot drift.
    """

    return pair_wire(
        [[str(getattr(member, name)) for name in _PAIR_MEMBER_FIELDS] for member in members]
    )


def pair_tokens(value: str) -> tuple[tuple[str, ...], ...]:
    """The member pairs one wire value names, each split at the arrow."""

    return tuple(tuple(part.split(_PAIR_ARROW)) for part in value.split(_SCOPE_SEPARATOR) if part)


def pair_from_wire(value: str, fields: tuple[str, ...]) -> list[dict[str, str]]:
    """One pair collection's authored value, decoded from its wire form.

    Dumped as plain mappings rather than built as models, exactly as ``scope_from_wire`` is: the wire
    form carries no vocabulary, so the reading is validated against the fact field's own member model
    when the statement is built, which is what refuses a token that family never declared and a pair
    with the wrong number of members.
    """

    return [dict(zip(fields, members, strict=False)) for members in pair_tokens(value)]


def authored_dimension(kind: DimensionKind, value: str) -> object:
    """One dimension's authored value, from the text a proposal or an editor widget carries.

    The one conversion point both authoring paths share, so a boolean, a scope or a pair collection
    cannot be decoded one way from a proposal and another way from the dialog that builds the same
    fact.
    """

    if kind == "boolean":
        return value == "true"
    if kind == "scope":
        return scope_from_wire(value)
    if kind == "pair_sequence":
        return pair_from_wire(value, _PAIR_MEMBER_FIELDS)
    return value


def _mentions(text: str, keyword: str) -> bool:
    """Whether one declared keyword occurs in one sentence, on word boundaries.

    Case-sensitive exactly when the keyword itself carries an uppercase letter. A keyword such as
    an earthing-arrangement designation must not be matched by the ordinary lowercase word that
    spells it, while a lowercase engineering term should still be found where a sentence happens
    to open with it. Word boundaries rather than a substring search, so a term is not found inside
    a longer word that means something else.
    """

    flags = 0 if any(character.isupper() for character in keyword) else re.IGNORECASE
    return re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text, flags) is not None


def _valid_keyword(keyword: str) -> bool:
    return (
        keyword == keyword.strip()
        and bool(keyword)
        and len(keyword) <= _MAX_KEYWORD_LENGTH
        and len(keyword.split()) <= _MAX_KEYWORD_WORDS
    )


class ClauseKeywordRule(FrozenModel):
    """One dimension value the wording of a sentence settles.

    Every keyword must occur in the sentence and no excluded keyword may. A rule with no
    keywords at all and only exclusions is how a dimension records that a sentence restricts
    it to nothing -- the ``any_*`` tokens -- which is a different claim from a dimension no
    rule settled.
    """

    dimension: str = Field(min_length=1)
    value: str = Field(min_length=1)
    keywords: tuple[str, ...] = ()
    #: Keywords whose presence disqualifies this rule, so a broader term can still be declared
    #: where a narrower reading of the same dimension shares it.
    excluded_keywords: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _keywords_are_short_terms(self) -> ClauseKeywordRule:
        if not self.keywords and not self.excluded_keywords:
            raise ValueError("a clause keyword rule that names no keyword matches every sentence")
        for keyword in (*self.keywords, *self.excluded_keywords):
            if not _valid_keyword(keyword):
                raise ValueError(
                    "a clause keyword must be a short term of at most "
                    f"{_MAX_KEYWORD_WORDS} words and {_MAX_KEYWORD_LENGTH} characters"
                )
        if set(self.keywords) & set(self.excluded_keywords):
            raise ValueError("a keyword cannot both be required and disqualify its own rule")
        return self

    def matches(self, text: str) -> bool:
        return all(_mentions(text, keyword) for keyword in self.keywords) and not any(
            _mentions(text, keyword) for keyword in self.excluded_keywords
        )


class ClauseSequenceRule(FrozenModel):
    """One pair-collection dimension read as ordered pairs of a declared token scale.

    Some dimensions are not settled by which term occurs but by the order two of them occur in:
    a step over a scale names its start and its end, and the same token can be either. Tokens are
    found in the order the sentence states them and paired two at a time, so a sentence stating
    several steps yields **one** reading naming all of them. A trailing unpaired token settles
    nothing.

    One dimension rather than two: a sentence stating several steps states one collection of pairs,
    and filling two independent scalar dimensions produced one draft per step -- which authored as
    several statements, and read as a cartesian product of the endpoints once more than one step was
    named.
    """

    #: Declared token to vocabulary value, longest token first at match time so a shorter token
    #: that prefixes a longer one cannot claim it.
    tokens: tuple[tuple[str, str], ...] = Field(min_length=1)
    #: The pair-collection dimension these pairs fill.
    dimension: str = Field(min_length=1)

    @model_validator(mode="after")
    def _tokens_are_distinct_short_terms(self) -> ClauseSequenceRule:
        if len({token for token, _value in self.tokens}) != len(self.tokens):
            raise ValueError("a clause sequence rule declares each token once")
        for token, _value in self.tokens:
            if not _valid_keyword(token):
                raise ValueError("a clause sequence token must be a short term")
        return self

    def pairs(self, text: str) -> tuple[tuple[str, str], ...]:
        by_token = dict(self.tokens)
        alternation = "|".join(
            re.escape(token) for token in sorted(by_token, key=len, reverse=True)
        )
        found = [
            by_token[match.group()]
            for match in re.finditer(rf"(?<!\w)(?:{alternation})(?!\w)", text)
        ]
        return tuple(zip(found[0::2], found[1::2], strict=False))


class ClauseFactGrammar(FrozenModel):
    """One route's declared rules for proposing the dimensions of one statement kind.

    Validated against that kind's own model at construction: a dimension the variant does not
    declare, or a value outside that dimension's vocabulary, would otherwise propose a reading
    no reviewer could author and no editor could show.
    """

    fact_kind: str
    #: Which of the family's statement kinds these rules propose, for a family that declares
    #: variants; empty for a family that states one kind. Declared rather than inferred, because a
    #: grammar's rules only make sense against one variant's dimensions -- and a kind a grammar
    #: cannot reach is a statement a reviewer authors by hand, not one this file may guess at.
    statement_kind: str = ""
    keyword_rules: tuple[ClauseKeywordRule, ...] = ()
    sequence_rules: tuple[ClauseSequenceRule, ...] = ()
    #: Dimensions every sentence of the route shares, such as the identifier of another route
    #: this one defers to. Applied first, so a keyword rule still wins where both speak.
    constants: dict[str, str] = Field(default_factory=dict)
    #: Dimensions a bullet may read from the sentence it completes when its own text settles
    #: them nowhere. Declared per grammar rather than per rule, and only for dimensions a
    #: bullet genuinely cannot carry alone: a list item's modality lives in its stem's verb.
    #: A fallback, never an addition -- a bullet stating its own value keeps it, and never gets
    #: a second draft from the stem.
    inherited_dimensions: tuple[str, ...] = ()

    @property
    def variant(self) -> str | None:
        """The statement kind these rules propose, spelled as ``fact_dimensions`` expects it."""

        return self.statement_kind or None

    @model_validator(mode="after")
    def _dimensions_and_values_are_the_families_own(self) -> ClauseFactGrammar:
        if self.fact_kind not in FACT_MODELS_BY_KIND:
            raise ValueError(f"unknown fact family: {self.fact_kind}")
        try:
            declared = fact_dimensions(self.fact_kind, self.variant)
        except RulePackageError as error:
            raise ValueError(str(error)) from error
        vocabularies = {name: options for name, _kind, options in declared}
        for dimension, value in (
            *((rule.dimension, rule.value) for rule in self.keyword_rules),
            *self.constants.items(),
        ):
            if dimension not in vocabularies:
                raise ValueError(f"{self.fact_kind} declares no dimension {dimension}")
            options = vocabularies[dimension]
            if options and value not in options:
                raise ValueError(f"{self.fact_kind}.{dimension} declares no value {value}")
        unknown_inherited = sorted(set(self.inherited_dimensions) - set(vocabularies))
        if unknown_inherited:
            raise ValueError(f"{self.fact_kind} declares no dimension {unknown_inherited[0]}")
        pairs = {name for name, kind, _options in declared if kind == "pair_sequence"}
        for rule in self.sequence_rules:
            if rule.dimension not in vocabularies:
                raise ValueError(f"{self.fact_kind} declares no dimension {rule.dimension}")
            # A sequence rule's reading *is* a collection of pairs, so a scalar dimension could not
            # hold it: caught where it is declared rather than as a validation error at the moment a
            # reviewer presses Author.
            if rule.dimension not in pairs:
                raise ValueError(f"{self.fact_kind}.{rule.dimension} holds no pairs")
            unknown = {
                value for _token, value in rule.tokens if value not in vocabularies[rule.dimension]
            }
            if unknown:
                raise ValueError(
                    f"{self.fact_kind}.{rule.dimension} declares no value {min(unknown)}"
                )
        return self


class ClauseSentence(FrozenModel):
    """One normative sentence of one fragment node.

    ``text`` and ``stem_text`` are licensed clause text read from the private draft. They exist
    to be shown beside a proposal so a maintainer confirms a reading against its own wording,
    and must never be written to a committed file.
    """

    fragment_id: Identifier
    node_order: int = Field(ge=0)
    node_kind: str
    node_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=4_000)
    #: The sentence this one completes, for a bullet that completes one: the nearest preceding
    #: paragraph sentence of the same fragment ending in a colon. Empty for anything else. A
    #: bullet of a list has no finite verb of its own, so a dimension carried by the verb can
    #: only be read from the stem -- see ``ClauseFactGrammar.inherited_dimensions``.
    stem_text: str = Field(default="", max_length=4_000)


class ClauseFactProposal(FrozenModel):
    """One draft statement: the dimensions a sentence settled, and the ones it did not.

    Never stored and never a review. ``unchosen`` is the honest half: a dimension no rule
    settled stays out of ``chosen`` rather than defaulting to an ``any_*`` token, because
    "this sentence does not restrict that dimension" and "we could not tell" are different
    claims and only the first is a reading.
    """

    rule_route: Identifier
    fact_kind: str
    #: Which of the family's statement kinds this draft is of; empty for a one-kind family. Carried
    #: on the draft rather than derived from ``chosen``, because it decides *which* dimensions the
    #: draft has to settle before any of them is read.
    statement_kind: str = ""
    sentence_index: int = Field(ge=0)
    sentence_text: str = Field(min_length=1, max_length=4_000)
    node_references: tuple[CitedNode, ...] = Field(min_length=1)
    #: Dimension to authored value, booleans spelled as their two text values.
    chosen: dict[str, str] = Field(default_factory=dict)
    unchosen: tuple[str, ...] = ()

    @property
    def fully_proposed(self) -> bool:
        return not self.unchosen


#: One implementation of "propose readings for this sentence". Zero or more readings per
#: sentence, each a partial map of dimension to authored value; a later slice may add a
#: model-based implementation behind this same call.
SentenceProposer = Callable[[ClauseSentence], tuple[Mapping[str, str], ...]]

#: A ``NOTE`` prefix is a structural marker, not source phrasing. Everything from the first one
#: to the end of a node is skipped: its text would otherwise both extend the preceding sentence
#: past its own end and propose readings of its own.
_NOTE_MARKER = re.compile(r"(?<!\w)NOTE(?!\w)")

#: A period, whitespace, and a capital. The lookahead is what keeps a mid-sentence period from
#: splitting a statement: an abbreviation or a clause identifier is followed by a lower-case word,
#: a closing bracket or a digit, never by a new sentence's capital.
_SENTENCE_BREAK = re.compile(r"(?<=\.)\s+(?=[A-Z])")


def _sentences(text: str) -> tuple[str, ...]:
    marker = _NOTE_MARKER.search(text)
    normative = text[: marker.start()] if marker else text
    return tuple(part.strip() for part in _SENTENCE_BREAK.split(normative) if part.strip())


def clause_sentences(fragment: RawClauseFragment) -> tuple[ClauseSentence, ...]:
    """Every normative sentence of a fragment, in reading order, with its node's citation.

    Sentence boundaries are structure, not content: one node can carry several distinct
    normative statements, and a node's own trailing notes are not statements at all. Each
    sentence keeps the node it came from so a draft built from it cites exactly that node.

    A bullet also keeps the stem it completes: the most recent paragraph sentence of this
    fragment ending in a colon. Tracked across the whole fragment rather than within a node or
    a segment, because a list's lead-in and its items are routinely split across both -- a
    subclause can open its list at the foot of one page and continue it on the next.
    """

    sentences: list[ClauseSentence] = []
    stem = ""
    for node in fragment.nodes:
        digest = canonical_model_sha256(node)
        for text in _sentences(node.raw_text):
            sentences.append(
                ClauseSentence(
                    fragment_id=fragment.id,
                    node_order=node.order,
                    node_kind=node.kind,
                    node_sha256=digest,
                    index=len(sentences),
                    text=text,
                    stem_text=stem if node.kind == "bullet" else "",
                )
            )
            if node.kind == "paragraph" and text.endswith(":"):
                stem = text
    return tuple(sentences)


def keyword_proposer(grammar: ClauseFactGrammar) -> SentenceProposer:
    """The declared grammar as one sentence proposer.

    A sentence restricting a **scope** dimension to several values yields **one** reading whose
    scope names all of them: that is one statement, and expanding it into one draft per value was
    where a single sentence turned into several identical-looking drafts and, once authored, into
    several projected rows for one reading.

    A sentence restricting a scalar dimension to several values still yields one reading per value,
    and a sentence multiplying several such dimensions yields their cartesian product: a consumer
    asks with one concrete value, and a scalar field cannot carry a set. The families whose
    remaining scalar dimensions state disjunctions gain their own scopes in the later slices.

    A declared inherited dimension its own text settles nowhere is then read from the sentence's
    stem. Second, and only into an empty dimension, so inheritance can neither override a
    bullet's own reading nor multiply it into two drafts.
    """

    scopes = {
        name
        for name, kind, _options in fact_dimensions(grammar.fact_kind, grammar.variant)
        if kind == "scope"
    }

    def propose(sentence: ClauseSentence) -> tuple[Mapping[str, str], ...]:
        by_dimension: dict[str, list[str]] = {}
        for rule in grammar.keyword_rules:
            if rule.matches(sentence.text):
                values = by_dimension.setdefault(rule.dimension, [])
                if rule.value not in values:
                    values.append(rule.value)
        if sentence.stem_text:
            for rule in grammar.keyword_rules:
                if (
                    rule.dimension in grammar.inherited_dimensions
                    and rule.dimension not in by_dimension
                    and rule.matches(sentence.stem_text)
                ):
                    by_dimension.setdefault(rule.dimension, []).append(rule.value)
        axes: list[list[dict[str, str]]] = [
            [{dimension: scope_wire(DimensionScope[str].of(*values))}]
            if dimension in scopes
            else [{dimension: value} for value in values]
            for dimension, values in by_dimension.items()
        ]
        for sequence in grammar.sequence_rules:
            pairs = sequence.pairs(sentence.text)
            if pairs:
                # One reading naming every pair, never one per pair: the same union a scope gets,
                # for the same reason -- a sentence stating several steps states one collection.
                axes.append([{sequence.dimension: pair_wire(pairs)}])
        readings: list[dict[str, str]] = [dict(grammar.constants)]
        for axis in axes:
            readings = [{**base, **choice} for base in readings for choice in axis]
        return tuple(readings)

    return propose


def propose_clause_facts(
    fragment: RawClauseFragment,
    *,
    rule_route: str,
    fact_kind: str,
    statement_kind: str | None = None,
    propose: SentenceProposer,
    locked: Mapping[str, str] = MappingProxyType({}),
) -> tuple[ClauseFactProposal, ...]:
    """One draft per reading per sentence, for one route's own fragment and one statement kind.

    Every sentence yields at least one draft, so the reviewer starts from the clause's own
    statements rather than from a blank editor. ``locked`` carries the dimensions the route
    itself determines rather than the sentence, and a reading never overrides one.

    A route whose family declares variants is proposed one kind at a time: which dimensions a draft
    must settle depends on the kind of reading it is, and a family's other kinds are authored by
    hand until a grammar reaches them.
    """

    dimensions = tuple(name for name, _kind, _options in fact_dimensions(fact_kind, statement_kind))
    proposals: list[ClauseFactProposal] = []
    for sentence in clause_sentences(fragment):
        citation = CitedNode(
            fragment_id=sentence.fragment_id,
            node_order=sentence.node_order,
            node_sha256=sentence.node_sha256,
        )
        for reading in propose(sentence):
            chosen = {**reading, **locked}
            proposals.append(
                ClauseFactProposal(
                    rule_route=rule_route,
                    fact_kind=fact_kind,
                    statement_kind=statement_kind or "",
                    sentence_index=sentence.index,
                    sentence_text=sentence.text,
                    node_references=(citation,),
                    chosen={name: chosen[name] for name in dimensions if name in chosen},
                    unchosen=tuple(name for name in dimensions if name not in chosen),
                )
            )
    return tuple(proposals)


def proposed_fact(proposal: ClauseFactProposal, *, statement_index: int) -> SupplyFact:
    """The typed statement one fully proposed draft records, ready to be authored.

    Refuses a draft with any unchosen dimension rather than filling one in: the whole point of
    keeping it unchosen is that nobody has read it yet.
    """

    if proposal.unchosen:
        raise ValueError(
            f"{proposal.rule_route} sentence {proposal.sentence_index} leaves "
            f"{list(proposal.unchosen)} unchosen"
        )
    variant = proposal.statement_kind or None
    kinds = {name: kind for name, kind, _options in fact_dimensions(proposal.fact_kind, variant)}
    values: dict[str, object] = {
        "statement_index": statement_index,
        "node_references": proposal.node_references,
        **{name: authored_dimension(kinds[name], value) for name, value in proposal.chosen.items()},
    }
    fact: SupplyFact = fact_model(proposal.fact_kind, variant).model_validate(values)
    return fact


__all__ = [
    "FACT_MODELS_BY_KIND",
    "SCOPE_UNRESTRICTED",
    "ClauseFactGrammar",
    "ClauseFactProposal",
    "ClauseKeywordRule",
    "ClauseSentence",
    "ClauseSequenceRule",
    "DimensionKind",
    "SentenceProposer",
    "authored_dimension",
    "clause_sentences",
    "fact_dimensions",
    "fact_model",
    "fact_variants",
    "keyword_proposer",
    "pair_from_wire",
    "pair_tokens",
    "pair_wire",
    "propose_clause_facts",
    "proposed_fact",
    "scope_from_wire",
    "scope_tokens",
    "scope_wire",
]
