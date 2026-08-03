from __future__ import annotations

from insulation_coordination.report.latex import breakable_latex_text
from insulation_coordination.report.revision_diff import (
    render_revision_diff,
    revision_of,
    revision_slug,
)


def _tex(revision: str, clearance: str) -> str:
    return "\n".join(
        [
            r"\begin{tabular}{@{}ll@{}}",
            r"Document & 1234 \\",
            rf"Revision & {revision} \\",
            r"\end{tabular}",
            r"\section{Results}",
            r"\subsection{HVP to PE}",
            rf"Clearance & {clearance} mm \\",
            r"\section{Advisories}",
            r"None recorded.",
            r"\section{Provenance}",
            r"Rules package SYNTHETIC.",
            r"\end{document}",
        ]
    )


def test_revision_is_read_from_the_generated_title_page() -> None:
    assert revision_of(_tex("01", "3.0")) == "01"


def test_missing_revision_line_returns_none() -> None:
    assert revision_of("no title page here") is None


def test_revision_slug_keeps_file_names_safe() -> None:
    assert revision_slug("1.0/draft b") == "1_0_draft_b"


def test_diff_keeps_changed_lines_and_drops_distant_unchanged_ones() -> None:
    diff = render_revision_diff(
        _tex("01", "3.0"), _tex("02", "4.5"), previous_revision="01", current_revision="02"
    )
    assert "revision 01 to revision 02" in diff
    assert breakable_latex_text(r"+Clearance & 4.5 mm \\") in diff
    assert breakable_latex_text(r"-Clearance & 3.0 mm \\") in diff
    assert breakable_latex_text("Rules package SYNTHETIC.") not in diff
    assert diff.startswith("\\documentclass")
    assert diff.rstrip().endswith(r"\end{document}")


def test_identical_sources_report_no_differences() -> None:
    same = _tex("01", "3.0")
    diff = render_revision_diff(same, same, previous_revision="01", current_revision="02")
    assert "identical in both revisions" in diff


def test_diff_escapes_latex_control_characters() -> None:
    diff = render_revision_diff(
        "a & b", "a \\& b_1", previous_revision="01", current_revision="02"
    )
    assert "\\textbackslash{}" in diff
    assert "\\_" in diff
    assert "\\&" in diff
