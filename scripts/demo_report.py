"""Generate a synthetic demo report with realistic voltages and configurations.

Usage:
    uv run python scripts/demo_report.py [output_dir] [--online]

Writes .tex, PDF, and compile log. Without --online, compilation requires a
warm Tectonic cache (run once with --online to populate it).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from insulation_coordination.calculation.engine import calculate_pair
from insulation_coordination.calculation.grouping import group_results
from insulation_coordination.project.resolver import resolve_effective_case
from insulation_coordination.report.compiler import compile_pdf
from insulation_coordination.report.latex import render_latex
from insulation_coordination.report.model import build_report_model
from insulation_coordination.report.tectonic import resolve_tectonic_runtime
from insulation_coordination.rules.archive import (
    load_rule_package,
    write_rule_package,
)
from scripts.create_release_fixtures import build_demo_project
from tests.fixtures.synthetic_rules import synthetic_hf_rule_package


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a synthetic demo report.")
    parser.add_argument("output_dir", nargs="?", default="generated-reports")
    parser.add_argument("--online", action="store_true", help="Allow network for first compile")
    args = parser.parse_args()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    rules_path = out / "synthetic.icrules"
    write_rule_package(rules_path, synthetic_hf_rule_package())
    rules = load_rule_package(rules_path)
    assert rules.package_sha256 is not None

    project = build_demo_project(rules)
    results = tuple(
        calculate_pair(resolve_effective_case(project.defaults, pair), rules)
        for pair in project.pairs
    )
    groups = group_results(results, project.group_splits)
    model = build_report_model(project, results, groups, rules)

    tex = out / "demo-report.tex"
    tex.write_text(render_latex(model), encoding="utf-8")
    pdf = out / "demo-report.pdf"

    try:
        runtime = resolve_tectonic_runtime()
    except ValueError as error:
        print(f"Wrote {tex}; {error}, PDF skipped.", file=sys.stderr)
        return 1

    result = compile_pdf(
        tex,
        pdf,
        runtime.command,
        offline_flag=runtime.offline_flag,
        cache_dir=runtime.cache_dir,
    )
    print(f"tex:  {tex}")
    print(f"pdf:  {result.pdf_path}")
    print(f"log:  {result.log_path}")
    if result.pdf_path is None:
        if args.online:
            print(result.stderr[-500:], file=sys.stderr)
        else:
            print(
                "PDF compile failed offline; the Tectonic cache is incomplete. "
                "Run once with --online to download the full resource bundle.",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
