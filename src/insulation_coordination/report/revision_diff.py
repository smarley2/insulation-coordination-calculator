"""Revision-to-revision report diff rendered as its own LaTeX document."""

from __future__ import annotations

import difflib
import re

from insulation_coordination.report.latex import breakable_latex_text, escape_latex_text

_REVISION_PATTERN = re.compile(r"^Revision & (?P<revision>.*?) \\\\$", re.MULTILINE)
_UNSAFE_IN_NAME = re.compile(r"[^A-Za-z0-9_-]")

# ponytail: plain textual diff of the generated .tex; latexdiff would need a
# second toolchain in the offline bundle.
#
# The font block mirrors report.tex.j2 so the offline Tectonic cache already
# holds every resource this document needs. No monospace font is requested:
# the bundle only carries the main report's typefaces.
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
\setlength{\parskip}{2pt}
\raggedright
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


def render_revision_diff(
    previous_tex: str,
    current_tex: str,
    *,
    previous_revision: str,
    current_revision: str,
) -> str:
    """Render only the lines that changed between two report revisions."""
    diff = list(
        difflib.unified_diff(
            previous_tex.splitlines(),
            current_tex.splitlines(),
            fromfile=f"revision {previous_revision}",
            tofile=f"revision {current_revision}",
            lineterm="",
            n=2,
        )
    )
    lines = [
        _PREAMBLE,
        r"\section*{Report differences}",
        (
            "Changes from revision "
            f"{escape_latex_text(previous_revision)} to revision "
            f"{escape_latex_text(current_revision)}."
            r"\par"
        ),
        r"\bigskip",
    ]
    body = diff[2:]  # drop the two ---/+++ file headers
    if not body:
        lines.append("The generated report source is identical in both revisions.")
    for entry in body:
        lines.append(rf"{{\small {breakable_latex_text(entry)}}}\par")
    lines.append(r"\end{document}")
    return "\n".join(lines) + "\n"
