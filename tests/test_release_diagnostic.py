from __future__ import annotations

import sys
from pathlib import Path

import pytest

from insulation_coordination.domain.project import RulePackageReference
from insulation_coordination.project.persistence import load_project, save_project_atomic
from insulation_coordination.release_diagnostic import (
    ReleaseDiagnosticError,
    render_release_tex,
    run_release_diagnostic,
)
from insulation_coordination.report.tectonic import TectonicRuntime
from scripts.create_release_fixtures import create_release_fixtures
from tests.fixtures.images import attachment_from, png_bytes


def _fake_tectonic(path: Path, exit_code: int = 0) -> tuple[str, str]:
    script = """from pathlib import Path
import sys
from pypdf import PdfWriter

outdir = Path(sys.argv[sys.argv.index("--outdir") + 1])
tex = Path(sys.argv[-1])
writer = PdfWriter()
writer.add_blank_page(width=612, height=792)
with (outdir / (tex.stem + ".pdf")).open("wb") as stream:
    writer.write(stream)
raise SystemExit(EXIT_CODE)
""".replace("EXIT_CODE", str(exit_code))
    script_path = path.with_suffix(".py")
    script_path.write_text(script, encoding="utf-8")
    return sys.executable, str(script_path)


@pytest.fixture
def release_fixture(tmp_path: Path) -> tuple[Path, Path]:
    destination = tmp_path / "release-smoke"
    create_release_fixtures(destination)
    return destination / "project.icproj", destination / "rules.icrules"


def test_release_diagnostic_loads_calculates_and_compiles(
    tmp_path: Path, release_fixture: tuple[Path, Path]
) -> None:
    project_path, rules_path = release_fixture
    runtime = TectonicRuntime(
        command=_fake_tectonic(tmp_path / "tectonic"),
        offline_flag="--only-cached",
        cache_dir=None,
        status="test",
    )

    result = run_release_diagnostic(project_path, rules_path, tmp_path / "output", runtime)

    assert result.success is True
    assert result.tex_path.exists()
    assert result.pdf_path is not None and result.pdf_path.exists()
    assert result.rules_sha256 == load_project(project_path).required_rules.sha256


def test_release_diagnostic_stages_an_attached_diagram_beside_the_tex(
    tmp_path: Path, release_fixture: tuple[Path, Path]
) -> None:
    project_path, rules_path = release_fixture
    project = load_project(project_path)
    attachment = attachment_from(png_bytes())
    save_project_atomic(project_path, project.model_copy(update={"circuit_diagram": attachment}))

    source = render_release_tex(project_path, rules_path, tmp_path / "output")

    staged = source.tex_path.parent / attachment.staged_filename
    assert staged.read_bytes() == attachment.decoded_bytes()
    assert f"{{{attachment.staged_filename}}}" in source.tex_path.read_text(encoding="utf-8")


def test_release_diagnostic_rejects_project_rules_hash_mismatch(
    tmp_path: Path, release_fixture: tuple[Path, Path]
) -> None:
    project_path, rules_path = release_fixture
    project = load_project(project_path)
    assert project.required_rules is not None
    mismatched = project.model_copy(
        update={
            "required_rules": RulePackageReference(
                package_id=project.required_rules.package_id,
                version=project.required_rules.version,
                sha256="0" * 64,
            )
        }
    )
    save_project_atomic(project_path, mismatched)

    with pytest.raises(ReleaseDiagnosticError, match="rules package pin"):
        run_release_diagnostic(
            project_path,
            rules_path,
            tmp_path / "output",
            TectonicRuntime(
                command=_fake_tectonic(tmp_path / "tectonic"),
                offline_flag="--only-cached",
                cache_dir=None,
                status="test",
            ),
        )


def test_release_diagnostic_reports_compiler_failure(
    tmp_path: Path, release_fixture: tuple[Path, Path]
) -> None:
    project_path, rules_path = release_fixture
    result = run_release_diagnostic(
        project_path,
        rules_path,
        tmp_path / "output",
        TectonicRuntime(
            command=_fake_tectonic(tmp_path / "tectonic", exit_code=7),
            offline_flag="--only-cached",
            cache_dir=None,
            status="test",
        ),
    )

    assert result.success is False
    assert result.pdf_path is None
    assert result.log_path.exists()


def test_release_diagnostic_rejects_symlink_tex_output(
    tmp_path: Path, release_fixture: tuple[Path, Path], symlinks_allowed: None
) -> None:
    project_path, rules_path = release_fixture
    output = tmp_path / "output"
    output.mkdir()
    victim = tmp_path / "victim.tex"
    victim.write_text("preserve", encoding="utf-8")
    (output / "release-diagnostic.tex").symlink_to(victim)

    with pytest.raises(ReleaseDiagnosticError, match="regular file"):
        render_release_tex(project_path, rules_path, output)

    assert victim.read_text(encoding="utf-8") == "preserve"
