"""Scanner unit tests using synthetic forbidden/allowed content only.

Every seeded value below is deliberately artificial; nothing in this file
reproduces licensed IEC content.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from scripts.scan_licensed_content import Finding, main, scan_tree


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text), encoding="utf-8")


def _categories(findings: tuple[Finding, ...]) -> set[str]:
    return {finding.category for finding in findings}


def test_clean_tree_has_no_findings(tmp_path: Path) -> None:
    _write(tmp_path, "src/module.py", 'GREETING = "hello"\n')
    _write(tmp_path, "docs/note.md", "Table Q.7 uses row geometry only.\n")
    assert scan_tree(tmp_path) == ()


def test_numeric_series_with_unit_labels_is_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/options.py",
        """
        from decimal import Decimal

        OPTIONS = (
            ("1.1 kV", Decimal(1111)),
            ("2.2 kV", Decimal(2222)),
            ("3.3 kV", Decimal(3333)),
            ("4.4 kV", Decimal(4444)),
            ("5.5 kV", Decimal(5555)),
            ("6.6 kV", Decimal(6666)),
        )
        """,
    )
    findings = scan_tree(tmp_path)
    assert [finding.category for finding in findings] == ["numeric-series"]
    assert findings[0].line == 4


def test_sibling_series_are_each_flagged_and_nested_ones_once(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/series.py",
        """
        # iec60001 context
        FIRST = ("1.5", "2.5", "3.5", "4.5", "5.5")
        SECOND = (("6.5", "7.5", "8.5"), ("9.5", "10.5", "11.5"))
        """,
    )
    findings = scan_tree(tmp_path)
    assert [(finding.line, finding.category) for finding in findings] == [
        (3, "numeric-series"),
        (4, "numeric-series"),
    ]


def test_small_integer_index_tuples_are_structural(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/geometry.py",
        """
        # iec60001 layout geometry: row indexes are permitted locators.
        DATA_ROWS = (1, 2, 3, 4, 5, 6, 7, 8)
        """,
    )
    assert scan_tree(tmp_path) == ()


def test_inline_factor_in_calculation_code_is_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/insulation_coordination/calculation/example.py",
        """
        from decimal import Decimal


        def treat(value: Decimal) -> Decimal:
            scaled = value * Decimal(1000)  # unit conversion: allowed
            return scaled * Decimal("9.9")
        """,
    )
    findings = scan_tree(tmp_path)
    assert [finding.category for finding in findings] == ["inline-factor"]
    assert findings[0].line == 7


def test_inline_threshold_in_calculation_code_is_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/insulation_coordination/calculation/limits.py",
        """
        from decimal import Decimal


        def route(value: Decimal, count: int) -> bool:
            if count < 0 or count == 1:  # bare small numbers: allowed
                return False
            return value > Decimal(77777)
        """,
    )
    findings = scan_tree(tmp_path)
    assert [finding.category for finding in findings] == ["inline-threshold"]
    assert findings[0].line == 8


def test_string_repetition_is_not_a_factor(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/insulation_coordination/calculation/format.py",
        'def pad(count: int) -> str:\n    return "0" * count\n',
    )
    assert scan_tree(tmp_path) == ()


def test_sentence_case_recipe_text_is_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/insulation_coordination/rules/importer/recipes/example.py",
        """
        SPEC = dict(
            title_anchor="Table Q.7",
            neutral="lowercase neutral description",
            suspicious="Copied Source Heading Text",
        )
        """,
    )
    findings = scan_tree(tmp_path)
    assert [finding.category for finding in findings] == ["source-like-text"]
    assert findings[0].line == 5


def test_document_value_next_to_table_identifier_is_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "docs/spec.md",
        """
        Table Q.7 spans two pages.
        Table Q.7 returns 9.9 mm at the synthetic level.
        """,
    )
    findings = scan_tree(tmp_path)
    assert [finding.category for finding in findings] == ["value-near-table-id"]
    assert findings[0].line == 3


def test_long_numeric_series_in_document_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "docs/series.md", "levels: 1.1, 2.2, 3.3, 4.4, 5.5, 6.6, 7.7\n")
    assert _categories(scan_tree(tmp_path)) == {"text-numeric-series"}


def test_private_artifact_types_are_flagged(tmp_path: Path) -> None:
    (tmp_path / "rules.icrules").write_bytes(b"private")
    (tmp_path / "audit-inventory.json").write_text("{}", encoding="utf-8")
    findings = scan_tree(tmp_path)
    assert [finding.category for finding in findings] == ["private-artifact", "private-artifact"]


def test_synthetic_fixture_claiming_iec_source_is_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/fixtures/example_rules.py",
        """
        def synthetic_package():
            return dict(standard="IEC 60001-1", edition="1")
        """,
    )
    findings = scan_tree(tmp_path)
    assert [finding.category for finding in findings] == ["synthetic-iec-source"]


def test_private_test_tree_is_not_checked_for_iec_sources(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/private/conftest.py",
        'synthetic = dict(standard="IEC 60001-1")\n',
    )
    assert scan_tree(tmp_path) == ()


@pytest.mark.parametrize(("arguments", "expected"), (((), 0), (("--strict",), 1)))
def test_main_is_report_only_unless_strict(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    arguments: tuple[str, ...],
    expected: int,
) -> None:
    (tmp_path / "rules.icrules").write_bytes(b"private")
    assert main([str(tmp_path), *arguments]) == expected
    output = capsys.readouterr().out
    assert "private-artifact" in output
    assert "1 finding(s)" in output


def test_main_reports_zero_findings_for_clean_tree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(tmp_path), "--strict"]) == 0
    assert "0 finding(s)" in capsys.readouterr().out
