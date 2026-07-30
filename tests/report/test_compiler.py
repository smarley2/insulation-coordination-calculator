import shutil
from pathlib import Path

import pytest
from pypdf import PdfReader

from insulation_coordination.report.compiler import CompileError, compile_pdf


def _fake_tectonic(path: Path, *, exit_code: int = 0, produce_pdf: bool = True) -> Path:
    script = f"""#!/usr/bin/env python3
from pathlib import Path
import sys
from pypdf import PdfWriter

print("|".join(sys.argv[1:]))
print("synthetic compiler diagnostic", file=sys.stderr)
if {produce_pdf!r}:
    outdir = Path(sys.argv[sys.argv.index("--outdir") + 1])
    tex = Path(sys.argv[-1])
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with (outdir / (tex.stem + ".pdf")).open("wb") as stream:
        writer.write(stream)
raise SystemExit({exit_code})
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)
    return path


def test_compile_pdf_uses_offline_argv_and_validates_output(tmp_path: Path) -> None:
    tex = tmp_path / "source report.tex"
    tex.write_text(r"\documentclass{article}\begin{document}Synthetic\end{document}")
    marker = tmp_path / "shell-marker"
    tectonic = _fake_tectonic(tmp_path / "fake compiler;touch shell-marker")
    output = tmp_path / "renamed report.pdf"

    result = compile_pdf(tex, output, tectonic)

    assert result.success is True
    assert result.returncode == 0
    assert result.pdf_path == output.resolve()
    assert len(PdfReader(output).pages) == 1
    assert f"--offline|--outdir|{tmp_path.resolve()}|{tex.resolve()}" in result.stdout
    assert result.stderr == "synthetic compiler diagnostic\n"
    assert result.log_path.read_text(encoding="utf-8").startswith("returncode: 0\n")
    assert not marker.exists()


def test_compile_pdf_retains_tex_and_log_on_compiler_failure(tmp_path: Path) -> None:
    tex = tmp_path / "failure.tex"
    tex.write_text("synthetic source", encoding="utf-8")
    tectonic = _fake_tectonic(tmp_path / "fake-tectonic", exit_code=7, produce_pdf=True)
    output = tmp_path / "failure.pdf"

    result = compile_pdf(tex, output, tectonic)

    assert result.success is False
    assert result.returncode == 7
    assert result.pdf_path is None
    assert tex.read_text(encoding="utf-8") == "synthetic source"
    assert result.log_path.exists()
    assert "synthetic compiler diagnostic" in result.log_path.read_text(encoding="utf-8")
    assert not output.exists()


def test_compile_pdf_rejects_success_without_a_valid_pdf(tmp_path: Path) -> None:
    tex = tmp_path / "missing-output.tex"
    tex.write_text("synthetic source", encoding="utf-8")
    tectonic = _fake_tectonic(tmp_path / "fake-tectonic", produce_pdf=False)

    result = compile_pdf(tex, tmp_path / "missing-output.pdf", tectonic)

    assert result.success is False
    assert "did not produce" in result.stderr
    assert result.log_path.exists()


@pytest.mark.parametrize(
    ("tex_name", "output_name"),
    [
        ("source.txt", "output.pdf"),
        ("source.tex", "output.txt"),
        ("same.tex", "same.tex"),
    ],
)
def test_compile_pdf_rejects_unsafe_path_contracts(
    tmp_path: Path, tex_name: str, output_name: str
) -> None:
    tex = tmp_path / tex_name
    tex.write_text("synthetic", encoding="utf-8")
    tectonic = _fake_tectonic(tmp_path / "fake-tectonic")

    with pytest.raises(CompileError):
        compile_pdf(tex, tmp_path / output_name, tectonic)


@pytest.mark.skipif(shutil.which("tectonic") is None, reason="Tectonic is not installed")
def test_real_tectonic_offline_integration_when_available(tmp_path: Path) -> None:
    tex = tmp_path / "integration.tex"
    tex.write_text(
        r"\documentclass{article}\begin{document}Synthetic report\end{document}",
        encoding="utf-8",
    )
    output = tmp_path / "integration.pdf"
    tectonic = Path(shutil.which("tectonic") or "")

    result = compile_pdf(tex, output, tectonic)

    assert result.success, result.log_path.read_text(encoding="utf-8")
    assert len(PdfReader(output).pages) == 1
