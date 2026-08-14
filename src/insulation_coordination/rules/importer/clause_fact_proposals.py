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
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Literal, get_args

from pydantic import Field, model_validator

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import Identifier, RulePackageError
from insulation_coordination.rules.importer.clause_facts import (
    BarrierTransferFact,
    CitedNode,
    HfAttenuationFact,
    PropagationStepFact,
    SpdMonitoringFact,
    SpdReductionFact,
    SupplyFact,
    SystemVoltageFact,
)
from insulation_coordination.rules.importer.clauses import RawClauseFragment
from insulation_coordination.rules.importer.extract import canonical_model_sha256

FactModel = type[
    SystemVoltageFact
    | PropagationStepFact
    | BarrierTransferFact
    | SpdReductionFact
    | SpdMonitoringFact
    | HfAttenuationFact
]

#: The one model each declared fact family builds. The single source the editor, the proposer
#: and the recipe's own family checks all read, so a family added to one of them and forgotten
#: in another cannot happen.
FACT_MODEL_BY_KIND: dict[str, FactModel] = {
    "system_voltage": SystemVoltageFact,
    "propagation_step": PropagationStepFact,
    "barrier_transfer": BarrierTransferFact,
    "spd_reduction": SpdReductionFact,
    "spd_monitoring": SpdMonitoringFact,
    "hf_attenuation": HfAttenuationFact,
}

#: ``fact_kind`` is the family itself, fixed per route; ``statement_index`` has its own spinner;
#: ``node_references`` come from the node reader, never typed by hand.
_UNDIMENSIONED_FIELDS = frozenset({"fact_kind", "statement_index", "node_references"})

DimensionKind = Literal["choice", "boolean", "identifier"]

#: A boolean dimension's two authored values. Spelled as text because that is what an editor
#: offers and what a declared rule states; converted once, in ``proposed_fact``.
_BOOLEAN_VALUES = ("true", "false")

#: The longest a declared keyword may be. Keywords are short generic engineering terms; this cap
#: is what stops a whole clause sentence from being pasted into a public file as a "keyword".
_MAX_KEYWORD_WORDS = 4
_MAX_KEYWORD_LENGTH = 40


def fact_dimensions(fact_kind: str) -> tuple[tuple[str, DimensionKind, tuple[str, ...]], ...]:
    """Each authored dimension of one fact family with its widget kind and vocabulary.

    Read from the model's own annotations, so neither the editor nor a declared rule carries a
    hand-written copy of a vocabulary that could drift from the model it has to build. A boolean
    is a two-value choice starting unchosen -- a reviewer must never record a reading they did
    not pick, and a checkbox has no unchosen state. An ``Identifier`` field has no vocabulary and
    gets a line edit. Anything else is refused here rather than degrading silently: a dimension
    the editor cannot offer is a fact no reviewer can author, and approval would block on the
    route with nothing to explain why.
    """

    dimensions: list[tuple[str, DimensionKind, tuple[str, ...]]] = []
    for name, field in FACT_MODEL_BY_KIND[fact_kind].model_fields.items():
        if name in _UNDIMENSIONED_FIELDS:
            continue
        if field.annotation is bool:
            dimensions.append((name, "boolean", _BOOLEAN_VALUES))
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
    """Two dimensions read as ordered pairs of one declared token scale.

    Some dimensions are not settled by which term occurs but by the order two of them occur in:
    a step over a scale names its start and its end, and the same token can be either. Tokens are
    found in the order the sentence states them and paired two at a time, so a sentence stating
    several steps yields one reading per step. A trailing unpaired token settles nothing.
    """

    #: Declared token to vocabulary value, longest token first at match time so a shorter token
    #: that prefixes a longer one cannot claim it.
    tokens: tuple[tuple[str, str], ...] = Field(min_length=1)
    dimensions: tuple[str, str]

    @model_validator(mode="after")
    def _tokens_and_dimensions_are_distinct(self) -> ClauseSequenceRule:
        if self.dimensions[0] == self.dimensions[1]:
            raise ValueError("a clause sequence rule fills two different dimensions")
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
    """One route's declared rules for proposing the dimensions of its fact family.

    Validated against the family's own model at construction: a dimension the family does not
    declare, or a value outside that dimension's vocabulary, would otherwise propose a reading
    no reviewer could author and no editor could show.
    """

    fact_kind: str
    keyword_rules: tuple[ClauseKeywordRule, ...] = ()
    sequence_rules: tuple[ClauseSequenceRule, ...] = ()
    #: Dimensions every sentence of the route shares, such as the identifier of another route
    #: this one defers to. Applied first, so a keyword rule still wins where both speak.
    constants: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _dimensions_and_values_are_the_families_own(self) -> ClauseFactGrammar:
        if self.fact_kind not in FACT_MODEL_BY_KIND:
            raise ValueError(f"unknown fact family: {self.fact_kind}")
        vocabularies = {name: options for name, _kind, options in fact_dimensions(self.fact_kind)}
        for dimension, value in (
            *((rule.dimension, rule.value) for rule in self.keyword_rules),
            *self.constants.items(),
        ):
            if dimension not in vocabularies:
                raise ValueError(f"{self.fact_kind} declares no dimension {dimension}")
            options = vocabularies[dimension]
            if options and value not in options:
                raise ValueError(f"{self.fact_kind}.{dimension} declares no value {value}")
        for rule in self.sequence_rules:
            for dimension in rule.dimensions:
                if dimension not in vocabularies:
                    raise ValueError(f"{self.fact_kind} declares no dimension {dimension}")
                unknown = {
                    value for _token, value in rule.tokens if value not in vocabularies[dimension]
                }
                if unknown:
                    raise ValueError(
                        f"{self.fact_kind}.{dimension} declares no value {min(unknown)}"
                    )
        return self


class ClauseSentence(FrozenModel):
    """One normative sentence of one fragment node.

    ``text`` is licensed clause text read from the private draft. It exists to be shown beside a
    proposal so a maintainer confirms a reading against its own wording, and must never be
    written to a committed file.
    """

    fragment_id: Identifier
    node_order: int = Field(ge=0)
    node_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=4_000)


class ClauseFactProposal(FrozenModel):
    """One draft statement: the dimensions a sentence settled, and the ones it did not.

    Never stored and never a review. ``unchosen`` is the honest half: a dimension no rule
    settled stays out of ``chosen`` rather than defaulting to an ``any_*`` token, because
    "this sentence does not restrict that dimension" and "we could not tell" are different
    claims and only the first is a reading.
    """

    rule_route: Identifier
    fact_kind: str
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
    """

    sentences: list[ClauseSentence] = []
    for node in fragment.nodes:
        digest = canonical_model_sha256(node)
        for text in _sentences(node.raw_text):
            sentences.append(
                ClauseSentence(
                    fragment_id=fragment.id,
                    node_order=node.order,
                    node_sha256=digest,
                    index=len(sentences),
                    text=text,
                )
            )
    return tuple(sentences)


def keyword_proposer(grammar: ClauseFactGrammar) -> SentenceProposer:
    """The declared grammar as one sentence proposer.

    A sentence restricting a dimension to several values yields one reading per value, and a
    sentence multiplying several dimensions yields their cartesian product: a consumer always
    asks with one concrete value, so a row per concrete value is what a projector needs, and an
    ``any_*`` token would wrongly answer for the values the sentence leaves out.
    """

    def propose(sentence: ClauseSentence) -> tuple[Mapping[str, str], ...]:
        by_dimension: dict[str, list[str]] = {}
        for rule in grammar.keyword_rules:
            if rule.matches(sentence.text):
                values = by_dimension.setdefault(rule.dimension, [])
                if rule.value not in values:
                    values.append(rule.value)
        axes: list[list[dict[str, str]]] = [
            [{dimension: value} for value in values] for dimension, values in by_dimension.items()
        ]
        for sequence in grammar.sequence_rules:
            pairs = sequence.pairs(sentence.text)
            if pairs:
                axes.append([dict(zip(sequence.dimensions, pair, strict=True)) for pair in pairs])
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
    propose: SentenceProposer,
    locked: Mapping[str, str] = MappingProxyType({}),
) -> tuple[ClauseFactProposal, ...]:
    """One draft per reading per sentence, for one route's own fragment.

    Every sentence yields at least one draft, so the reviewer starts from the clause's own
    statements rather than from a blank editor. ``locked`` carries the dimensions the route
    itself determines rather than the sentence, and a reading never overrides one.
    """

    dimensions = tuple(name for name, _kind, _options in fact_dimensions(fact_kind))
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
    booleans = {
        name for name, kind, _options in fact_dimensions(proposal.fact_kind) if kind == "boolean"
    }
    values: dict[str, object] = {
        "statement_index": statement_index,
        "node_references": proposal.node_references,
        **{
            name: (value == "true") if name in booleans else value
            for name, value in proposal.chosen.items()
        },
    }
    fact: SupplyFact = FACT_MODEL_BY_KIND[proposal.fact_kind].model_validate(values)
    return fact


__all__ = [
    "FACT_MODEL_BY_KIND",
    "ClauseFactGrammar",
    "ClauseFactProposal",
    "ClauseKeywordRule",
    "ClauseSentence",
    "ClauseSequenceRule",
    "DimensionKind",
    "SentenceProposer",
    "clause_sentences",
    "fact_dimensions",
    "keyword_proposer",
    "propose_clause_facts",
    "proposed_fact",
]
