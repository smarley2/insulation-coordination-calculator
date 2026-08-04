from __future__ import annotations

from insulation_coordination.report.revision_diff import (
    readable_report_lines,
    render_revision_diff,
    revision_of,
    revision_slug,
)


def _tex(revision: str, clearance: str) -> str:
    return "\n".join(
        [
            r"\begin{document}",
            r"\begin{tabular}{@{}ll@{}}",
            r"Document & 1234 \\",
            rf"Revision & {revision} \\",
            r"\end{tabular}",
            r"\section{Pair Comparison Matrices}",
            r"\subsection{Required clearance}",
            r"\toprule",
            rf"HVP & \textemdash & {clearance} mm \\",
            r"\bottomrule",
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


def test_readable_lines_keep_content_with_its_chapter_and_drop_layout() -> None:
    lines = readable_report_lines(_tex("01", "3.0"))

    assert ("", "Document | 1234") in lines
    assert ("Pair Comparison Matrices — Required clearance", "HVP | — | 3.0 mm") in lines
    assert ("Advisories", "None recorded.") in lines
    assert not any("tabular" in text for _heading, text in lines)
    assert not any("toprule" in text for _heading, text in lines)


def test_readable_lines_split_the_items_the_template_joins() -> None:
    joined = r"""\begin{document}
\section{Grouped Calculations}
\begin{itemize}
\item First rule applied. \item Second rule applied.
\end{itemize}
\end{document}
"""

    assert readable_report_lines(joined) == (
        ("Grouped Calculations", "First rule applied."),
        ("Grouped Calculations", "Second rule applied."),
    )


def test_diff_reports_changed_content_as_was_and_now_under_its_chapter() -> None:
    diff = render_revision_diff(
        _tex("01", "3.0"), _tex("02", "4.5"), previous_revision="01", current_revision="02"
    )

    assert "revision 01 to revision 02" in diff
    assert r"\subsection*{Pair Comparison Matrices — Required clearance}" in diff
    assert r"\textbf{was:} HVP | — | 3.0 mm\par" in diff
    assert r"\textbf{now:} HVP | — | 4.5 mm\par" in diff
    assert "Rules package SYNTHETIC." not in diff
    assert r"\begin{tabular}" not in diff.split(r"\begin{document}", 1)[1]
    assert "allowbreak" not in diff
    assert diff.startswith("\\documentclass")
    assert diff.rstrip().endswith(r"\end{document}")


def test_diff_labels_added_and_removed_content() -> None:
    previous = r"""\begin{document}
\section{Advisories}
\end{document}
"""
    current = r"""\begin{document}
\section{Advisories}
\item \textbf{FIELD\_CHECK}: Confirm the field classification.
\end{document}
"""

    diff = render_revision_diff(previous, current, previous_revision="01", current_revision="02")

    assert r"\textbf{added:} FIELD\_CHECK: Confirm the field classification.\par" in diff
    assert (
        r"\textbf{removed:}"
        in render_revision_diff(current, previous, previous_revision="02", current_revision="03")
    )


def test_identical_sources_report_no_differences() -> None:
    same = _tex("01", "3.0")
    diff = render_revision_diff(same, same, previous_revision="01", current_revision="02")

    assert "report the same content" in diff


def test_diff_escapes_report_text_without_reading_it_as_markup() -> None:
    diff = render_revision_diff(
        r"\begin{document} a & b",
        "\\begin{document}\n" + r"a \& b\_1 \textbackslash{}input\{unsafe\}",
        previous_revision="01",
        current_revision="02",
    )

    assert r"a \& b\_1 \textbackslash{}input\{unsafe\}" in diff
