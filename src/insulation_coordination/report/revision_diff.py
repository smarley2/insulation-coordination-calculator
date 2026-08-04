"""Revision-to-revision report diff rendered as its own LaTeX document."""

from __future__ import annotations

import difflib
import re
from typing import NamedTuple

from insulation_coordination.report.latex import escape_latex_text

_REVISION_PATTERN = re.compile(r"^Revision & (?P<revision>.*?) \\\\$", re.MULTILINE)
_UNSAFE_IN_NAME = re.compile(r"[^A-Za-z0-9_-]")

# ponytail: the diff reads the two generated .tex files, the only artefacts kept
# per revision. It compares the readable content they carry rather than their
# source lines, so no report-model snapshot has to be persisted per revision and
# latexdiff stays out of the offline bundle.
_SECTION = re.compile(r"^\\(?P<level>sub)?section\*?\{\s*(?P<title>.*?)\s*\}$")
_PURE_MARKUP = re.compile(r"^\\[a-zA-Z@]+(?:\[[^]]*\])?(?:\{[^{}]*\})*$")
_ITEM_BREAK = re.compile(r"\\item\b|\\par\b")
_ENVIRONMENT = re.compile(r"\\(?:begin|end)\{[^{}]*\}")
_COMMAND_WITH_TEXT = re.compile(r"\\(?:textbf|textit|emph|paragraph|item)\b")
_ESCAPE_SEQUENCES = (
    (r"\textbackslash{}", "\\"),
    (r"\textasciitilde{}", "~"),
    (r"\textasciicircum{}", "^"),
    (r"\textemdash", "—"),
    (r"\textendash", "–"),
    (r"\allowbreak{}", ""),
    (r"\,", " "),
    (r"\&", "&"),
    (r"\%", "%"),
    (r"\_", "_"),
    (r"\#", "#"),
    (r"\$", "$"),
    (r"\{", "{"),
    (r"\}", "}"),
)

# The font block mirrors report.tex.j2 so the offline Tectonic cache already
# holds every resource this document needs.
_PREAMBLE = r"""\documentclass[10pt]{article}
\usepackage[a4paper,margin=18mm]{geometry}
\usepackage{lmodern}
\usepackage{fontspec}
\setmainfont{texgyrepagella}[
  Extension = .otf,
  UprightFont = *-regular,
  BoldFont = *-bold,
  ItalicFont = *-italic,
  BoldItalicFont = *-bolditalic,
]
\setlength{\parindent}{0pt}
\setlength{\parskip}{3pt}
\raggedright
\sloppy
\begin{document}
"""


def revision_of(tex: str) -> str | None:
    """Read the revision printed on a generated report's title page."""
    match = _REVISION_PATTERN.search(tex)
    if match is None:
        return None
    return match.group("revision").strip() or None


def revision_slug(revision: str) -> str:
    """Turn a revision string into a safe single file-name component."""
    return _UNSAFE_IN_NAME.sub("_", revision)


def readable_report_lines(tex: str) -> tuple[tuple[str, str], ...]:
    """Reduce a generated report to the readable lines it prints, with headings.

    Each entry is the chapter the line belongs to and the line as a reader sees
    it: table cells joined by ``|``, LaTeX escapes resolved, layout commands
    dropped. Comparing these instead of the source keeps the diff about the
    engineering content.
    """
    body = tex.split(r"\begin{document}", 1)[-1]
    lines: list[tuple[str, str]] = []
    section = ""
    subsection = ""
    for raw in body.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        heading = _SECTION.match(stripped)
        if heading is not None:
            title = _plain_text(heading.group("title"))
            if heading.group("level") is None:
                section, subsection = title, ""
            else:
                subsection = title
            continue
        heading_path = " — ".join(part for part in (section, subsection) if part)
        # The report template joins list items onto one source line; each item is
        # its own statement to a reader, so it is its own comparable line here.
        for fragment in _ITEM_BREAK.split(stripped):
            text = _plain_text(fragment)
            if text:
                lines.append((heading_path, text))
    return tuple(lines)


def render_revision_diff(
    previous_tex: str,
    current_tex: str,
    *,
    previous_revision: str,
    current_revision: str,
) -> str:
    """Render the report content that changed between two revisions."""
    previous = readable_report_lines(previous_tex)
    current = readable_report_lines(current_tex)
    changes = _changes(previous, current)
    lines = [
        _PREAMBLE,
        r"\section*{Report differences}",
        (
            "Changes from revision "
            f"{escape_latex_text(previous_revision)} to revision "
            f"{escape_latex_text(current_revision)}. Only changed report content "
            "is listed, by the chapter it appears in; layout and formatting are "
            "ignored." + r"\par"
        ),
        r"\bigskip",
    ]
    if not changes:
        lines.append("The two revisions report the same content.")
    heading = None
    for change in changes:
        if change.heading != heading:
            heading = change.heading
            lines.append(rf"\subsection*{{{escape_latex_text(heading) or 'Title page'}}}")
        lines.append(rf"\textbf{{{change.label}}} {escape_latex_text(change.text)}\par")
    lines.append(r"\end{document}")
    return "\n".join(lines) + "\n"


class _Change(NamedTuple):
    heading: str
    label: str
    text: str


def _changes(
    previous: tuple[tuple[str, str], ...],
    current: tuple[tuple[str, str], ...],
) -> tuple[_Change, ...]:
    """Label every differing line as was/now, removed, or added."""
    matcher = difflib.SequenceMatcher(
        a=[text for _heading, text in previous],
        b=[text for _heading, text in current],
        autojunk=False,
    )
    changes: list[_Change] = []
    for tag, previous_start, previous_end, current_start, current_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        removed = previous[previous_start:previous_end]
        added = current[current_start:current_end]
        if tag == "replace":
            for index in range(max(len(removed), len(added))):
                if index < len(removed):
                    heading, text = removed[index]
                    changes.append(_Change(heading, "was:", text))
                if index < len(added):
                    heading, text = added[index]
                    changes.append(_Change(heading, "now:", text))
            continue
        label = "removed:" if tag == "delete" else "added:"
        for heading, text in removed or added:
            changes.append(_Change(heading, label, text))
    return tuple(changes)


def _plain_text(latex: str) -> str:
    """Turn one generated LaTeX line into the text a reader sees, or ``""``."""
    text = latex.removesuffix(r"\\").strip()
    if text.startswith(("%", r"\begin{", r"\end{")):
        return ""
    if _PURE_MARKUP.match(text) and not _COMMAND_WITH_TEXT.search(text):
        return ""
    # Escape sequences are parked first: resolving them now would turn escaped
    # report text such as \textbackslash{}input into a command to strip.
    for index, (escaped, _plain) in enumerate(_ESCAPE_SEQUENCES):
        text = text.replace(escaped, f"\x00{index}\x00")
    text = _ENVIRONMENT.sub(" ", text)
    text = re.sub(r"\\[a-zA-Z@]+(?:\[[^]]*\])?", " ", text)
    # Braces vanish rather than becoming spaces: the command they belonged to
    # already left one, and "\textbf{X}:" must not read as "X :".
    text = text.replace("&", " | ").replace("{", "").replace("}", "")
    for index, (_escaped, plain) in enumerate(_ESCAPE_SEQUENCES):
        text = text.replace(f"\x00{index}\x00", plain)
    text = re.sub(r"\s*\|\s*", " | ", text)
    return re.sub(r"\s+", " ", text).strip(" |").strip()
