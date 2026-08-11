"""Guards the guidance prose's semantic-rule-id references against a silent rename.

``topology_guidance.py`` names IEC 62477-1:2022 semantic rule ids as literal strings in
its guidance text, in about nineteen places, rather than importing the ``semantic_ids``
constants (the module names the rule, it does not quote the standard). A rename of one
of those constants would leave a dangling reference in this user-facing help text with
nothing to catch it - a green suite and a broken pointer. This test extracts every such
reference from the registered guidance and checks it against the ids the importer
actually promises to keep stable, which is cheaper than rewriting the prose to use the
constants directly.
"""

from __future__ import annotations

import re

from insulation_coordination.rules.importer.iec62477_2022.semantic_ids import (
    REQUIRED_SEMANTIC_IDS,
)
from insulation_coordination.ui.topology_guidance import TopologyGuidanceId
from insulation_coordination.ui.voltage_guidance import guidance_for

#: A trailing "." ends the sentence, not the id, so the pattern requires each dotted
#: segment to start with a letter or underscore rather than swallowing punctuation.
_SEMANTIC_ID_PATTERN = re.compile(r"iec62477_2022\.[a-z_]+(?:\.[a-z_]+)*")


def _guidance_text(guidance_id: TopologyGuidanceId) -> str:
    guidance = guidance_for(guidance_id)
    return "\n".join(
        (guidance.title, guidance.short_text, guidance.detailed_text, *guidance.examples,
         *guidance.common_mistakes)
    )


def _is_known(reference: str) -> bool:
    """A required id, or a suffixed sibling of one - e.g. ``<base>.impulse_reference``.

    The projection emits such suffixed rule ids alongside the base one (see
    ``domain.dvc``); those are legitimate references and are never themselves listed in
    ``REQUIRED_SEMANTIC_IDS``, which holds only the base ids.
    """
    return reference in REQUIRED_SEMANTIC_IDS or any(
        reference.startswith(f"{base}.") for base in REQUIRED_SEMANTIC_IDS
    )


def test_every_semantic_rule_id_named_in_topology_guidance_text_is_real() -> None:
    references = {
        match
        for guidance_id in TopologyGuidanceId
        for match in _SEMANTIC_ID_PATTERN.findall(_guidance_text(guidance_id))
    }

    assert references, "expected at least one semantic rule id reference to check"
    unknown = {reference for reference in references if not _is_known(reference)}
    assert not unknown, f"guidance text names unknown semantic rule ids: {sorted(unknown)}"
