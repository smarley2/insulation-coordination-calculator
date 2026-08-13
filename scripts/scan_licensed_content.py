"""Report-only scanner for licensed-content risks in the public source tree.

Detects *structure*, never licensed values: no IEC series, table cell, heading
text, or clause wording appears in this file as a detection pattern. Each check
flags shapes that tend to carry licensed content (large numeric series near IEC
identifiers, literal factors in calculation code, source-like recipe text,
value-plus-table-identifier pairings in documents) and leaves classification to
human review.

Report-only by default: findings are printed and the exit code stays 0 so the
scanner can run before the issue-40 content migrations finish. ``--strict``
exits non-zero on findings and is intended for CI once the tree is clean.

Usage: python scripts/scan_licensed_content.py [ROOT] [--strict]
"""

from __future__ import annotations

import argparse
import ast
import math
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import NamedTuple

SKIP_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    ".claude",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "standards",
}
PRIVATE_SUFFIXES = {".pdf", ".icrules", ".icproj", ".pyc"}
PRIVATE_NAMES = {"audit-inventory.json"}
TEXT_SUFFIXES = {".md", ".tex", ".json", ".yaml", ".yml", ".txt"}

# Generic identifier shapes only: an IEC standard number, a table identifier such
# as "Table F.2", or an annex/clause reference. These are permitted structural
# locators; the scanner uses them purely as *context* that makes nearby numeric
# content suspicious.
IEC_CONTEXT = re.compile(r"(?i)\biec[\s-]*6\d{4}")
TABLE_OR_CLAUSE_ID = re.compile(
    r"\bTable\s+[A-Z]?\.?\d+|\b[A-Z]\.\d+\b|\bAnnex\s+[A-Z]\b|\bClause\s+\d"
)
VALUE_WITH_UNIT = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*(?:mm|kV|V|Hz|kHz|MHz|m)\b")
COMMA_NUMBER_SERIES = re.compile(r"(?:\d+(?:\.\d+)?\s*,\s*){5,}\d")
UNIT_BEARING_STRING = re.compile(r"\d\s*(?:mm|kV|V|Hz|kHz|MHz)\b")
# Sentence-case multi-word text that does not start with a structural locator
# keyword. Neutral internal descriptions in this repository are lowercase.
SOURCE_LIKE_STRING = re.compile(
    r"^(?!Table\b|Annex\b|Figure\b|Clause\b|Edition\b|IEC\b|Equation\b)"
    r"[A-Z][A-Za-z]*(?:\s+[A-Za-z0-9()%/-]+)+$"
)
IEC_SOURCE_REFERENCE = re.compile(r"standard\s*=\s*(?:\"IEC|'IEC|STANDARD\b)")

SERIES_MINIMUM_COUNT = 5
# Row/column index tuples are permitted structural geometry; a container whose
# numbers are all small integers is treated as indexes, not engineering values.
INDEX_LIKE_MAXIMUM = 64


class Finding(NamedTuple):
    path: Path
    line: int
    category: str
    description: str


def iter_files(root: Path) -> Iterator[Path]:
    """Tracked files when ``root`` is a git checkout, a filtered walk otherwise.

    Using ``git ls-files`` keeps explicitly private/untracked locations (the
    gitignored ``standards/`` folder, local rule packages) out of the scan.
    """
    try:
        listing = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        yield from _walk(root)
        return
    for name in listing.stdout.split("\0"):
        if name:
            path = root / name
            if path.is_file():
                yield path


def _walk(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_DIRECTORIES for part in relative.parts):
            continue
        yield path


def scan_tree(root: Path) -> tuple[Finding, ...]:
    root = Path(root).resolve()
    findings: list[Finding] = []
    for path in iter_files(root):
        findings.extend(scan_file(path, root))
    findings.sort(key=lambda finding: (str(finding.path), finding.line))
    return tuple(findings)


def scan_file(path: Path, root: Path) -> tuple[Finding, ...]:
    relative = path.relative_to(root)
    findings = list(_private_artifact(relative))
    suffix = path.suffix.lower()
    if suffix == ".py":
        text = _read(path)
        findings.extend(_python_findings(relative, text))
    elif suffix in TEXT_SUFFIXES:
        text = _read(path)
        findings.extend(_text_findings(relative, text))
    return tuple(findings)


def _private_artifact(relative: Path) -> Iterator[Finding]:
    if relative.suffix.lower() in PRIVATE_SUFFIXES or relative.name in PRIVATE_NAMES:
        yield Finding(
            relative,
            0,
            "private-artifact",
            "private or generated artifact type committed to the public tree",
        )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _text_findings(relative: Path, text: str) -> Iterator[Finding]:
    for number, line in enumerate(text.splitlines(), start=1):
        if TABLE_OR_CLAUSE_ID.search(line) and VALUE_WITH_UNIT.search(line):
            yield Finding(
                relative,
                number,
                "value-near-table-id",
                "engineering value paired with a table/clause identifier",
            )
        if COMMA_NUMBER_SERIES.search(line):
            yield Finding(
                relative,
                number,
                "text-numeric-series",
                "long comma-separated numeric series in a document",
            )


def _python_findings(relative: Path, text: str) -> Iterator[Finding]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return
    yield from _numeric_series(relative, text, tree)
    parts = relative.parts
    if parts[:3] == ("src", "insulation_coordination", "calculation"):
        yield from _inline_factors(relative, tree)
    if "recipes" in parts:
        yield from _source_like_strings(relative, tree)
    if parts and parts[0] == "tests" and "private" not in parts:
        yield from _synthetic_iec_source(relative, text)


def _numeric_series(relative: Path, text: str, tree: ast.Module) -> Iterator[Finding]:
    """Large numeric containers in an IEC context or carrying unit-bearing labels."""
    file_mentions_iec = bool(IEC_CONTEXT.search(text))
    flagged: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Tuple | ast.List | ast.Set):
            continue
        numbers, unit_strings = _count_numeric_descendants(node)
        if len(numbers) < SERIES_MINIMUM_COUNT:
            continue
        if all(value == int(value) and abs(value) < INDEX_LIKE_MAXIMUM for value in numbers):
            continue
        if not (file_mentions_iec or unit_strings):
            continue
        if any(child in flagged for child in _descendant_ids(node)):
            continue
        flagged.update(_descendant_ids(node))
        yield Finding(
            relative,
            node.lineno,
            "numeric-series",
            f"container with {len(numbers)} numeric literals in an IEC/unit context",
        )


def _descendant_ids(node: ast.AST) -> set[int]:
    # Only positioned nodes: expression-context markers such as ast.Load are
    # shared singletons, and counting them would make every container look like
    # a descendant of the first flagged one.
    return {id(child) for child in ast.walk(node) if hasattr(child, "lineno")}


def _count_numeric_descendants(node: ast.AST) -> tuple[list[float], bool]:
    numbers: list[float] = []
    unit_strings = False
    for child in ast.walk(node):
        if not isinstance(child, ast.Constant):
            continue
        value = child.value
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            numbers.append(float(value))
        elif isinstance(value, str):
            try:
                parsed = float(value)
            except ValueError:
                if UNIT_BEARING_STRING.search(value):
                    unit_strings = True
            else:
                if math.isfinite(parsed):
                    numbers.append(parsed)
    return numbers, unit_strings


def _inline_factors(relative: Path, tree: ast.Module) -> Iterator[Finding]:
    """Literal factors and comparison thresholds inside calculation code."""
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            operands: tuple[ast.expr, ...] = (node.left, node.right)
            category, description = (
                "inline-factor",
                "literal multiplicative factor in calculation code",
            )
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Mult):
            operands = (node.value,)
            category, description = (
                "inline-factor",
                "literal multiplicative factor in calculation code",
            )
        elif isinstance(node, ast.Compare):
            # Bare small numbers in comparisons (index checks, sign checks) are
            # ordinary code; only Decimal(...) constants and large numeric
            # literals look like engineering thresholds.
            operands = tuple(
                operand
                for operand in (node.left, *node.comparators)
                if not _is_small_bare_number(operand)
            )
            category, description = (
                "inline-threshold",
                "literal comparison threshold in calculation code",
            )
        else:
            continue
        if any(_is_literal_factor(operand) for operand in operands):
            yield Finding(relative, node.lineno, category, description)


def _is_small_bare_number(node: ast.expr) -> bool:
    value = _constant_number(node, allow_string=False)
    return value is not None and abs(value) < INDEX_LIKE_MAXIMUM


def _is_literal_factor(node: ast.expr) -> bool:
    # A bare string constant in a Mult is string repetition, not arithmetic, so
    # only numeric constants count; a Decimal("...") argument is arithmetic.
    value = _constant_number(node, allow_string=False)
    if (
        value is None
        and isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Decimal"
        and node.args
    ):
        value = _constant_number(node.args[0], allow_string=True)
    if value is None:
        return False
    return not _is_power_of_ten(value)


def _constant_number(node: ast.expr, *, allow_string: bool) -> float | None:
    if isinstance(node, ast.Constant) and not isinstance(node.value, bool):
        if isinstance(node.value, int | float):
            return float(node.value)
        if allow_string and isinstance(node.value, str):
            try:
                return float(node.value)
            except ValueError:
                return None
    return None


def _is_power_of_ten(value: float) -> bool:
    if value <= 0:
        return False
    while value < 1:
        value *= 10
    while value >= 10:
        value /= 10
    return value == 1


def _source_like_strings(relative: Path, tree: ast.Module) -> Iterator[Finding]:
    """Sentence-case text in importer recipes; neutral descriptions are lowercase."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            children: Iterable[ast.expr] = (
                *node.args,
                *(keyword.value for keyword in node.keywords),
            )
        elif isinstance(node, ast.Tuple | ast.List):
            children = node.elts
        else:
            continue
        for child in children:
            if (
                isinstance(child, ast.Constant)
                and isinstance(child.value, str)
                and SOURCE_LIKE_STRING.match(child.value)
            ):
                yield Finding(
                    relative,
                    child.lineno,
                    "source-like-text",
                    "sentence-case text in a recipe; neutral descriptions are lowercase",
                )


def _synthetic_iec_source(relative: Path, text: str) -> Iterator[Finding]:
    if "fixtures" not in relative.parts and "conftest" not in relative.name:
        return
    if "synthetic" not in text.lower():
        return
    for number, line in enumerate(text.splitlines(), start=1):
        if IEC_SOURCE_REFERENCE.search(line):
            yield Finding(
                relative,
                number,
                "synthetic-iec-source",
                "synthetic fixture uses an IEC standard identity as its source",
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", help="tree to scan")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero when findings exist (for CI once the tree is clean)",
    )
    arguments = parser.parse_args(argv)
    findings = scan_tree(Path(arguments.root))
    for finding in findings:
        print(
            f"{finding.path.as_posix()}:{finding.line}: {finding.category}: {finding.description}"
        )
    counts = Counter(finding.category for finding in findings)
    total = sum(counts.values())
    summary = ", ".join(f"{category}={count}" for category, count in sorted(counts.items()))
    print(f"{total} finding(s){': ' + summary if summary else ''}")
    return 1 if arguments.strict and findings else 0


if __name__ == "__main__":
    sys.exit(main())
