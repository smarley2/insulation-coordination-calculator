"""The README's workflow contract, held where a machine can check it.

Four properties, and the last one is the reason this module exists at all.

*The sections are the application's own.* The four workflow headings are named, and the two
annex-named headings they replaced are refused, so nobody restores a presentation in which an
IEC annex is this application's top-level workflow.

*Every semantic rule role the README names is a real one.* A role is a promise about what the
approved package supplies; a role that no longer exists is a promise nothing keeps. The set is
read from ``semantic_ids`` rather than restated here, so renaming an identifier fails this test
instead of silently rotting the README.

*Every Mermaid diagram parses.* A diagram that does not render is invisible on GitHub and
nothing else notices. The parser here is deliberately small - node terms, arrows, and the rule
that every referenced node is labelled somewhere - which is enough to catch the typos a
handwritten flowchart actually collects.

*No workflow section states a figure.* This is the guard ``scripts/scan_licensed_content.py``
cannot give. Its heuristics look for a value beside a table identifier, so both leaks found
while this section was being written were invisible to it: a boundary written as a bare
numeral with nothing beside it, and a factor written as an English word. The rule here is
inverted and therefore has no such blind spot - inside a workflow section every digit must
belong to a standard, clause, table, annex, equation or issue identifier, and the words that
spell a quantity out are refused outright.
"""

from __future__ import annotations

import re
from pathlib import Path

from insulation_coordination.rules.importer.iec62477_2022.semantic_ids import (
    REQUIRED_SEMANTIC_IDS,
)

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")

WORKFLOW_HEADINGS = (
    "## Insulation-coordination workflow",
    "## Clearance calculation workflow",
    "## Creepage calculation workflow",
    "## Verification handoff",
)

#: A term of a flowchart line: a node id, optionally carrying a box or decision label.
TERM = re.compile(r'(?P<id>[A-Za-z_]\w*)\s*(?:\[(?P<box>"[^"]*")\]|\{(?P<decision>"[^"]*")\})?')
#: An arrow between two terms, with or without an edge label.
LINK = re.compile(r'\s*(?:--\s*"[^"]*"\s*)?-->\s*')

#: The only shapes a digit may take inside a workflow section. Everything here is a locator -
#: a document, a clause, a table, an annex, an equation or an issue - and none of it is a
#: value. Anything else that carries a digit is a figure this repository must not publish.
IDENTIFIER = re.compile(
    r"""
      IEC\s\d{5}(?:-\d)?(?::\d{4})?   # IEC 60664-1, IEC 62477-1:2022
    | iec\d{5}[-_][\w.\-]+            # iec60664-1-f2, iec62477_2022.clearance.requirements
    | Table\s\d+                      # table identifiers
    | Annex\s[A-Z]
    | Part\s\d
    | Equation\s\(\d\)
    | \b[A-Z]\.\d+\b                  # annex artifact identifiers such as F.2
    | \#\d+                           # issue references
    """,
    re.VERBOSE,
)

#: Multipliers and quantities spelled as words, which no numeral heuristic can see.
SPELLED_OUT = re.compile(
    r"(?i)\b(?:"
    r"twice|thrice|doubles?|doubled|doubling|triples?|tripled|quadrupled?|halves|halved|half"
    r"|(?:one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|sixty"
    r"|seventy|eighty|ninety|hundred|thousand)\s+"
    r"(?:times|percent|per\s+cent|hertz|kilohertz|megahertz|volts?|kilovolts?"
    r"|millimet(?:re|er)s?|met(?:re|er)s?)"
    r")\b"
)


def _section(heading: str) -> str:
    """The body under ``heading``, up to the next top-level heading."""

    start = README.index(heading) + len(heading)
    rest = README[start:]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def _mermaid_blocks(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"```mermaid\n(.*?)```", text, flags=re.DOTALL))


def _parse_flowchart(block: str) -> tuple[set[str], set[str]]:
    """The labelled and the referenced node ids of one flowchart, or an assertion failure."""

    lines = [line.strip() for line in block.splitlines() if line.strip()]
    assert lines, "empty mermaid block"
    assert lines[0] == "flowchart TD", f"unexpected diagram header {lines[0]!r}"
    labelled: set[str] = set()
    referenced: set[str] = set()
    for line in lines[1:]:
        position = 0
        expecting_term = True
        while position < len(line):
            match = (TERM if expecting_term else LINK).match(line, position)
            assert match is not None, f"cannot parse {line!r} from column {position}"
            if expecting_term:
                referenced.add(match["id"])
                if match["box"] or match["decision"]:
                    labelled.add(match["id"])
            position = match.end()
            expecting_term = not expecting_term
        assert not expecting_term, f"{line!r} ends on an arrow"
    return labelled, referenced


def test_readme_uses_application_owned_workflow_sections() -> None:
    for heading in WORKFLOW_HEADINGS:
        assert README.count(heading) == 1, f"{heading!r} must appear exactly once"


def test_readme_removes_obsolete_annex_named_workflow_headings() -> None:
    assert "## Annex G clearance workflow" not in README
    assert "## Annex H creepage workflow" not in README
    assert "## Pair-specific critical-frequency flow" not in README


def test_high_frequency_stays_subordinate_to_the_clearance_workflow() -> None:
    assert "### High-frequency clearance subflow" in _section("## Clearance calculation workflow")


def test_readme_states_rules_are_loaded_from_private_package() -> None:
    assert "active approved `.icrules` package" in README
    assert "calculator's own data flow" in README


def test_named_semantic_rule_roles_exist() -> None:
    named = set(re.findall(r"iec62477_2022\.[a-z_]+\.[a-z_]+", README))
    assert named, "the workflows should name the semantic rule roles they depend on"
    assert named <= REQUIRED_SEMANTIC_IDS, sorted(named - REQUIRED_SEMANTIC_IDS)


def test_workflow_diagrams_parse() -> None:
    blocks = tuple(
        block for heading in WORKFLOW_HEADINGS for block in _mermaid_blocks(_section(heading))
    )
    assert len(blocks) >= len(WORKFLOW_HEADINGS), "every workflow section needs its diagram"
    for block in blocks:
        labelled, referenced = _parse_flowchart(block)
        assert referenced - labelled == set(), f"unlabelled node(s) {referenced - labelled}"


def test_workflow_sections_state_no_figure() -> None:
    for heading in WORKFLOW_HEADINGS:
        residue = IDENTIFIER.sub(" ", _section(heading))
        offenders = [line for line in residue.splitlines() if re.search(r"\d", line)]
        assert not offenders, f"{heading!r} states a figure: {offenders}"


def test_workflow_sections_state_no_spelled_out_quantity() -> None:
    for heading in WORKFLOW_HEADINGS:
        offenders = SPELLED_OUT.findall(_section(heading))
        assert not offenders, f"{heading!r} spells a quantity out: {offenders}"
