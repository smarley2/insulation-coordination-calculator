"""Resolves the semantic rule ids named in this application's guidance to their sources.

Guidance prose is this application's own engineering writing: it explains what a choice
means and what it affects, and it names the semantic rule that decides each consequence -
``iec62477_2022.supply.system_voltage_resolution`` and its siblings - rather than quoting a
standard. That naming is only half a reference, though. A reader who wants to check the
claim needs the clause, table and page the rule was read from, and those belong to the
active rule package, not to the prose.

So the prose stays the single place a rule is named, and this module reads the provenance
back out of the package at display time. Nothing here invents a clause number: a rule the
active package does not carry resolves to ``None``, which the caller shows as an absence
rather than filling in. That distinction is the point - application guidance and
package-derived normative provenance must never look like each other.
"""

from __future__ import annotations

import re
from typing import Protocol

from insulation_coordination.domain.frozen_model import FrozenModel
from insulation_coordination.domain.rules import Identifier, RulePackage, SourceReference

#: A trailing "." ends the sentence, not the id, so each dotted segment must start with a
#: letter or an underscore rather than swallowing the punctuation after it.
_SEMANTIC_ID_PATTERN = re.compile(r"iec62477_2022\.[a-z_]+(?:\.[a-z_]+)*")


class _Sourced(Protocol):
    """Every rule kind in a package carries an id and the source it was read from."""

    @property
    def id(self) -> Identifier: ...

    @property
    def source(self) -> SourceReference: ...


class RuleProvenance(FrozenModel):
    """One named rule and where the active package read it from.

    ``source`` is ``None`` when the active package carries no rule under this id - because
    no package is loaded, or because this one does not cover that rule. It is never a
    stand-in for a reference nobody has looked up.
    """

    rule_id: Identifier
    source: SourceReference | None = None

    @property
    def available(self) -> bool:
        return self.source is not None


def referenced_rule_ids(text: str) -> tuple[Identifier, ...]:
    """Every semantic rule id ``text`` names, in the order it names them, without repeats."""
    ordered: dict[Identifier, None] = {}
    for match in _SEMANTIC_ID_PATTERN.findall(text):
        ordered.setdefault(match, None)
    return tuple(ordered)


def rule_provenance(package: RulePackage | None, text: str) -> tuple[RuleProvenance, ...]:
    """Resolve each rule id named in ``text`` against ``package``.

    ``package`` is ``None`` when none is loaded, which resolves every id to an absent
    source rather than raising: guidance stays readable without a package, it just cannot
    cite one.
    """
    sources = _sources_by_id(package)
    return tuple(
        RuleProvenance(rule_id=rule_id, source=sources.get(rule_id))
        for rule_id in referenced_rule_ids(text)
    )


def citation(source: SourceReference | None) -> str:
    """A one-line human citation for a source reference, or "" if there is none.

    Only the locating fields, in the order a reader would look them up. The standard's own
    identity strings and structural locators are all this needs; no cell content is
    involved.
    """
    if source is None:
        return ""
    parts = [f"{source.standard} {source.edition}"]
    if source.table:
        parts.append(f"Table {source.table}")
    if source.clause:
        parts.append(f"clause {source.clause}")
    if source.page is not None:
        parts.append(f"p.{source.page}")
    return ", ".join(parts)


def _sources_by_id(package: RulePackage | None) -> dict[Identifier, SourceReference]:
    if package is None:
        return {}
    groups: tuple[tuple[_Sourced, ...], ...] = (
        package.tables,
        package.formulas,
        package.decisions,
        package.procedures,
        package.guidance,
        package.curves,
    )
    return {rule.id: rule.source for group in groups for rule in group}


__all__ = [
    "RuleProvenance",
    "citation",
    "referenced_rule_ids",
    "rule_provenance",
]
