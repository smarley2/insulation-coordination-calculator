"""Small end-to-end diagnostic used by packaged release smoke tests."""

from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import dataclass
from pathlib import Path

from insulation_coordination.calculation.engine import (
    calculate_project_pair,
    derive_project_supply,
)
from insulation_coordination.calculation.grouping import group_results
from insulation_coordination.domain.project import FrozenModel, Project
from insulation_coordination.project.persistence import load_project
from insulation_coordination.report.compiler import compile_pdf
from insulation_coordination.report.latex import render_latex
from insulation_coordination.report.model import build_report_model
from insulation_coordination.report.tectonic import (
    TectonicRuntime,
    resolve_tectonic_runtime,
)
from insulation_coordination.rules.archive import load_rule_package


class ReleaseDiagnosticError(ValueError):
    """The packaged application cannot complete its end-to-end diagnostic."""


@dataclass(frozen=True)
class ReleaseReportSource:
    project_sha256: str
    rules_sha256: str
    tex_path: Path


class ReleaseDiagnosticResult(FrozenModel):
    success: bool
    project_sha256: str
    rules_sha256: str
    tex_path: Path
    pdf_path: Path | None
    log_path: Path


def render_release_tex(
    project_path: Path, rules_path: Path, output_dir: Path
) -> ReleaseReportSource:
    try:
        project = load_project(Path(project_path))
        rules = load_rule_package(Path(rules_path))
    except (OSError, ValueError) as error:
        raise ReleaseDiagnosticError(str(error)) from error
    if rules.package_sha256 is None:
        raise ReleaseDiagnosticError("rules package has no SHA-256 identity")
    if project.required_rules is None:
        raise ReleaseDiagnosticError("project has no rules package pin")
    expected = (
        project.required_rules.package_id,
        project.required_rules.version,
        project.required_rules.sha256,
    )
    actual = (str(rules.manifest.package_id), rules.manifest.version, rules.package_sha256)
    if expected != actual:
        raise ReleaseDiagnosticError("project rules package pin does not match the rules package")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        supply = derive_project_supply(project, rules)
        results = tuple(
            calculate_project_pair(project, pair, rules, supply=supply)
            for pair in project.pairs
            if not pair.is_excluded
        )
        groups = group_results(results, project.group_splits)
        model = build_report_model(project, results, groups, rules, image_directory=output_dir)
    except ValueError as error:
        raise ReleaseDiagnosticError(str(error)) from error

    tex_path = output_dir / "release-diagnostic.tex"
    _write_safe_text(tex_path, render_latex(model))
    return ReleaseReportSource(_project_sha256(project), rules.package_sha256, tex_path)


def run_release_diagnostic(
    project_path: Path,
    rules_path: Path,
    output_dir: Path,
    runtime: TectonicRuntime | None = None,
) -> ReleaseDiagnosticResult:
    source = render_release_tex(project_path, rules_path, output_dir)
    try:
        resolved = runtime or resolve_tectonic_runtime()
        compiled = compile_pdf(
            source.tex_path,
            Path(output_dir) / "release-diagnostic.pdf",
            resolved.command,
            offline_flag=resolved.offline_flag,
            cache_dir=resolved.cache_dir,
        )
    except (OSError, ValueError) as error:
        raise ReleaseDiagnosticError(str(error)) from error
    if not compiled.success:
        return ReleaseDiagnosticResult(
            success=False,
            project_sha256=source.project_sha256,
            rules_sha256=source.rules_sha256,
            tex_path=source.tex_path,
            pdf_path=None,
            log_path=compiled.log_path,
        )
    return ReleaseDiagnosticResult(
        success=True,
        project_sha256=source.project_sha256,
        rules_sha256=source.rules_sha256,
        tex_path=source.tex_path,
        pdf_path=compiled.pdf_path,
        log_path=compiled.log_path,
    )


def _project_sha256(project: Project) -> str:
    payload = json.dumps(
        project.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_safe_text(path: Path, content: str) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        mode = None
    except OSError as error:
        raise ReleaseDiagnosticError(f"diagnostic output cannot be inspected: {error}") from error
    if mode is not None and (stat.S_ISLNK(mode) or not stat.S_ISREG(mode)):
        raise ReleaseDiagnosticError("diagnostic TeX output must be a regular file")
    path.write_text(content, encoding="utf-8")
