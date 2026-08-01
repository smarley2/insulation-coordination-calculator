"""Safe offline wrapper for a pinned Tectonic executable."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from threading import Lock

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from insulation_coordination.domain.project import FrozenModel

# ponytail: global lock; use per-destination locks if compile throughput matters.
_COMPILE_LOCK = Lock()


class CompileError(ValueError):
    """Compiler paths violate the report export contract."""


class CompileResult(FrozenModel):
    success: bool
    returncode: int | None
    pdf_path: Path | None
    log_path: Path
    stdout: str
    stderr: str


type CommandPart = str | os.PathLike[str]
type CompilerCommand = CommandPart | Sequence[CommandPart]


def _normalize_command(command: CompilerCommand) -> list[str]:
    """Turn a single path or a command list into a list of string parts."""
    if isinstance(command, (str, os.PathLike)):
        return [os.fspath(command)]
    return [os.fspath(part) for part in command]


def _program(command: list[str], outdir: Path, tex: Path) -> Path:
    """Resolve the leading program path for validation."""
    if not command:
        raise CompileError("Tectonic command must not be empty")
    return _input_file(Path(command[0]), None, "Tectonic executable")


def compile_pdf(tex_path: Path, output_path: Path, tectonic: CompilerCommand) -> CompileResult:
    """Compile one LaTeX file in an isolated offline workspace."""
    tex = _input_file(tex_path, ".tex", "LaTeX source")
    command = _normalize_command(tectonic)
    program = _program(command, output_path, tex)
    output = _output_leaf(output_path, ".pdf", "PDF output")
    log_path = output.with_suffix(".compile.log")
    if output == tex or log_path == tex or program in {output, log_path}:
        raise CompileError("compiler, source, output, and log paths must be distinct")
    if not os.access(program, os.X_OK):
        raise CompileError("Tectonic executable is not executable")

    with _COMPILE_LOCK:
        _reject_unsafe_leaf(output, "PDF output")
        _reject_unsafe_leaf(log_path, "compiler log")
        output.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(prefix=".icc-tectonic-", dir=output.parent) as temporary:
            outdir = Path(temporary)
            produced = outdir / f"{tex.stem}.pdf"
            returncode, stdout, stderr = _run_tectonic(command, outdir, tex)
            pdf_path: Path | None = None
            success = False
            if returncode == 0:
                problem = _pdf_problem(produced)
                if problem is None:
                    try:
                        _atomic_copy(produced, output)
                    except OSError as error:
                        stderr += f"Could not promote compiled PDF: {error}\n"
                    else:
                        pdf_path = output
                        success = True
                else:
                    stderr += problem + "\n"
            _write_log(log_path, returncode, stdout, stderr)
    return CompileResult(
        success=success,
        returncode=returncode,
        pdf_path=pdf_path,
        log_path=log_path,
        stdout=stdout,
        stderr=stderr,
    )


def _run_tectonic(command: Sequence[str], outdir: Path, tex: Path) -> tuple[int | None, str, str]:
    try:
        completed = subprocess.run(
            [
                *_normalize_command(command),
                _offline_flag(command),
                "--outdir",
                str(outdir),
                str(tex),
            ],
            shell=False,
            timeout=120,
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.returncode, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as error:
        return (
            None,
            _stream_text(error.stdout),
            _stream_text(error.stderr) + "Tectonic timed out after 120 seconds\n",
        )
    except OSError as error:
        return None, "", f"Could not execute Tectonic: {error}\n"


def _input_file(path: Path, suffix: str | None, label: str) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as error:
        raise CompileError(f"{label} does not exist or is unsafe: {error}") from error
    if suffix is not None and resolved.suffix.lower() != suffix:
        raise CompileError(f"{label} path must have a {suffix} suffix")
    if not resolved.is_file():
        raise CompileError(f"{label} does not exist or is not a file")
    return resolved


def _output_leaf(path: Path, suffix: str, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.suffix.lower() != suffix:
        raise CompileError(f"{label} path must have a {suffix} suffix")
    try:
        parent = expanded.parent.resolve(strict=True)
    except OSError as error:
        raise CompileError(f"{label} parent does not exist or is unsafe: {error}") from error
    if not parent.is_dir():
        raise CompileError(f"{label} parent is not a directory")
    return parent / expanded.name


def _reject_unsafe_leaf(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    except OSError as error:
        raise CompileError(f"{label} leaf cannot be inspected safely: {error}") from error
    if stat.S_ISLNK(mode):
        raise CompileError(f"{label} leaf must not be a symlink")
    if not stat.S_ISREG(mode):
        raise CompileError(f"{label} leaf must be absent or a regular file")


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


def _atomic_copy(source: Path, destination: Path) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as target, source.open("rb") as source_stream:
            shutil.copyfileobj(source_stream, target)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _stream_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _write_log(path: Path, returncode: int | None, stdout: str, stderr: str) -> None:
    content = f"returncode: {returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _offline_flag(command: Sequence[str]) -> str:
    """Tectonic 0.15 uses --offline; newer versions renamed it to --only-cached."""
    try:
        completed = subprocess.run(
            [*_normalize_command(command), "--help"],
            shell=False,
            timeout=10,
            capture_output=True,
            text=True,
            check=False,
        )
        help_text = completed.stdout + completed.stderr
    except OSError:
        return "--offline"
    return "--only-cached" if "--only-cached" in help_text else "--offline"
