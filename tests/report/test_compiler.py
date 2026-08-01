import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from insulation_coordination.report.compiler import CompileError, compile_pdf


def _fake_tectonic(
    path: Path,
    *,
    exit_code: int = 0,
    produce_pdf: bool = True,
    valid_pdf: bool = True,
) -> tuple[str, str]:
    script_path = path.with_suffix(".py")
    script = f"""from pathlib import Path
import sys
from pypdf import PdfWriter

print("|".join(sys.argv[1:]))
print("synthetic compiler diagnostic", file=sys.stderr)
if {produce_pdf!r}:
    outdir = Path(sys.argv[sys.argv.index("--outdir") + 1])
    tex = Path(sys.argv[-1])
    output = outdir / (tex.stem + ".pdf")
    if {valid_pdf!r}:
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with output.open("wb") as stream:
            writer.write(stream)
    else:
        output.write_bytes(b"not a PDF")
raise SystemExit({exit_code})
"""
    script_path.write_text(script, encoding="utf-8")
    return sys.executable, str(script_path)


def _racing_fake_tectonic(path: Path) -> tuple[str, str]:
    script_path = path.with_suffix(".py")
    script = """from pathlib import Path
import sys
import time
from pypdf import PdfWriter

outdir = Path(sys.argv[sys.argv.index("--outdir") + 1])
tex = Path(sys.argv[-1])
title = tex.read_text(encoding="utf-8")
if title == "fast":
    time.sleep(0.1)
writer = PdfWriter()
writer.add_blank_page(width=612, height=792)
writer.add_metadata({"/Title": title})
with (outdir / (tex.stem + ".pdf")).open("wb") as stream:
    writer.write(stream)
if title == "slow":
    time.sleep(0.3)
print(str(tex))
"""
    script_path.write_text(script, encoding="utf-8")
    return sys.executable, str(script_path)


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
    arguments = result.stdout.strip().split("|")
    assert arguments[:2] == ["--offline", "--outdir"]
    assert Path(arguments[2]).parent == tmp_path.resolve()
    assert Path(arguments[2]).name.startswith(".icc-tectonic-")
    assert arguments[3] == str(tex.resolve())
    assert result.stderr == "synthetic compiler diagnostic\n"
    assert result.log_path.read_text(encoding="utf-8").startswith("returncode: 0\n")
    assert not marker.exists()
    assert not tuple(tmp_path.glob(".icc-tectonic-*"))


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
    ("failure", "expected_returncode"),
    [
        ("nonzero", 7),
        ("timeout", None),
        ("missing", 0),
        ("invalid", 0),
    ],
)
def test_failed_compile_removes_preexisting_regular_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    expected_returncode: int | None,
) -> None:
    tex = tmp_path / "source.tex"
    tex.write_text("source remains", encoding="utf-8")
    output = tmp_path / "output.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with output.open("wb") as stream:
        writer.write(stream)
    tectonic = _fake_tectonic(
        tmp_path / "fake-tectonic",
        exit_code=7 if failure == "nonzero" else 0,
        produce_pdf=failure not in {"missing", "timeout"},
        valid_pdf=failure != "invalid",
    )
    if failure == "timeout":

        def raise_timeout(*_args: object, **_kwargs: object) -> None:
            raise subprocess.TimeoutExpired(cmd="fake-tectonic", timeout=120)

        monkeypatch.setattr(subprocess, "run", raise_timeout)

    result = compile_pdf(tex, output, tectonic)

    assert result.success is False
    assert result.returncode == expected_returncode
    assert result.pdf_path is None
    assert not output.exists()
    assert tex.read_text(encoding="utf-8") == "source remains"
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


@pytest.mark.parametrize("leaf", ["pdf", "log"])
def test_compile_pdf_rejects_symlink_leaves_without_touching_victim(
    tmp_path: Path,
    leaf: str,
) -> None:
    tex = tmp_path / "source.tex"
    tex.write_text("synthetic", encoding="utf-8")
    tectonic = _fake_tectonic(tmp_path / "fake-tectonic")
    output = tmp_path / "output.pdf"
    log = output.with_suffix(".compile.log")
    victim = tmp_path / f"{leaf}-victim.txt"
    victim.write_text("do not change", encoding="utf-8")
    (output if leaf == "pdf" else log).symlink_to(victim)

    with pytest.raises(CompileError, match="symlink"):
        compile_pdf(tex, output, tectonic)

    assert victim.read_text(encoding="utf-8") == "do not change"
    assert (output if leaf == "pdf" else log).is_symlink()


@pytest.mark.parametrize("parent_kind", ["missing", "file"])
def test_compile_pdf_rejects_missing_or_non_directory_output_parent(
    tmp_path: Path,
    parent_kind: str,
) -> None:
    tex = tmp_path / "source.tex"
    tex.write_text("synthetic", encoding="utf-8")
    tectonic = _fake_tectonic(tmp_path / "fake-tectonic")
    parent = tmp_path / "output-parent"
    if parent_kind == "file":
        parent.write_text("not a directory", encoding="utf-8")

    with pytest.raises(CompileError, match="parent"):
        compile_pdf(tex, parent / "output.pdf", tectonic)


@pytest.mark.parametrize("same_destination", [False, True])
def test_concurrent_same_basename_compilations_are_isolated(
    tmp_path: Path,
    same_destination: bool,
) -> None:
    first_dir = tmp_path / "first-source"
    second_dir = tmp_path / "second-source"
    first_dir.mkdir()
    second_dir.mkdir()
    first_tex = first_dir / "report.tex"
    second_tex = second_dir / "report.tex"
    first_tex.write_text("slow", encoding="utf-8")
    second_tex.write_text("fast", encoding="utf-8")
    tectonic = _racing_fake_tectonic(tmp_path / "fake-tectonic")
    first_output = tmp_path / "shared.pdf" if same_destination else tmp_path / "first.pdf"
    second_output = tmp_path / "shared.pdf" if same_destination else tmp_path / "second.pdf"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(compile_pdf, first_tex, first_output, tectonic),
            executor.submit(compile_pdf, second_tex, second_output, tectonic),
        )
        results = tuple(future.result() for future in futures)

    assert all(result.success for result in results)
    assert str(first_tex.resolve()) in results[0].stdout
    assert str(second_tex.resolve()) in results[1].stdout
    if same_destination:
        assert PdfReader(first_output).metadata.title in {"slow", "fast"}
    else:
        assert PdfReader(first_output).metadata.title == "slow"
        assert PdfReader(second_output).metadata.title == "fast"
    assert not tuple(tmp_path.glob(".icc-tectonic-*"))


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
