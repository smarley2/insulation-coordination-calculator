"""Safe offline wrapper for a pinned Tectonic executable."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from insulation_coordination.domain.project import FrozenModel


class CompileError(ValueError):
    """Compiler paths violate the report export contract."""


class CompileResult(FrozenModel):
    success: bool
    returncode: int | None
    pdf_path: Path | None
    log_path: Path
    stdout: str
    stderr: str


def compile_pdf(tex_path: Path, output_path: Path, tectonic: Path) -> CompileResult:
    """Compile one LaTeX file offline and retain captured diagnostics."""
    tex = _input_file(tex_path, ".tex", "LaTeX source")
    executable = _input_file(tectonic, None, "Tectonic executable")
    output = output_path.expanduser().resolve()
    if output.suffix.lower() != ".pdf":
        raise CompileError("PDF output path must have a .pdf suffix")
    if output == tex:
        raise CompileError("LaTeX source and PDF output paths must differ")
    if not os.access(executable, os.X_OK):
        raise CompileError("Tectonic executable is not executable")

    output.parent.mkdir(parents=True, exist_ok=True)
    produced = output.parent / f"{tex.stem}.pdf"
    log_path = output.with_suffix(".compile.log")
    if executable in {output, produced, log_path} or tex == log_path:
        raise CompileError("compiler, source, output, and log paths must be distinct")
    for stale in {output, produced}:
        stale.unlink(missing_ok=True)

    try:
        completed = subprocess.run(
            [
                str(executable),
                "--offline",
                "--outdir",
                str(output.parent),
                str(tex),
            ],
            shell=False,
            timeout=120,
            capture_output=True,
            text=True,
            check=False,
        )
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        returncode = None
        stdout = _stream_text(error.stdout)
        stderr = _stream_text(error.stderr) + "Tectonic timed out after 120 seconds\n"
    except OSError as error:
        returncode = None
        stdout = ""
        stderr = f"Could not execute Tectonic: {error}\n"

    pdf_path: Path | None = None
    success = False
    if returncode == 0:
        problem = _pdf_problem(produced)
        if problem is None:
            if produced != output:
                produced.replace(output)
            pdf_path = output
            success = True
        else:
            stderr += problem + "\n"
            produced.unlink(missing_ok=True)
    else:
        produced.unlink(missing_ok=True)
    _write_log(log_path, returncode, stdout, stderr)
    return CompileResult(
        success=success,
        returncode=returncode,
        pdf_path=pdf_path,
        log_path=log_path,
        stdout=stdout,
        stderr=stderr,
    )


def _input_file(path: Path, suffix: str | None, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if suffix is not None and resolved.suffix.lower() != suffix:
        raise CompileError(f"{label} path must have a {suffix} suffix")
    if not resolved.is_file():
        raise CompileError(f"{label} does not exist or is not a file")
    return resolved


def _pdf_problem(path: Path) -> str | None:
    if not path.is_file():
        return "Tectonic did not produce the expected PDF"
    try:
        if not path.read_bytes().startswith(b"%PDF-"):
            return "Tectonic output is not a PDF"
        if len(PdfReader(path).pages) < 1:
            return "Tectonic output PDF has no pages"
    except (EOFError, OSError, PdfReadError, ValueError) as error:
        return f"Tectonic output PDF is invalid: {error}"
    return None


def _stream_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _write_log(path: Path, returncode: int | None, stdout: str, stderr: str) -> None:
    path.write_text(
        f"returncode: {returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}",
        encoding="utf-8",
    )
