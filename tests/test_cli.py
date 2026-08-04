from __future__ import annotations

import json
from pathlib import Path

import pytest

from insulation_coordination import __version__, cli, release_diagnostic
from insulation_coordination.release_diagnostic import (
    ReleaseDiagnosticError,
    ReleaseDiagnosticResult,
)
from insulation_coordination.startup import StartupKind, StartupRequest


def _result(output_dir: Path, *, success: bool) -> ReleaseDiagnosticResult:
    return ReleaseDiagnosticResult(
        success=success,
        project_sha256="a" * 64,
        rules_sha256="b" * 64,
        tex_path=output_dir / "release-diagnostic.tex",
        pdf_path=output_dir / "release-diagnostic.pdf" if success else None,
        log_path=output_dir / "release-diagnostic.log",
    )


@pytest.fixture
def captured_gui(monkeypatch: pytest.MonkeyPatch) -> list[StartupRequest]:
    """Replace the GUI launch so startup routing is testable without Qt."""
    requests: list[StartupRequest] = []

    def fake_run_gui(request: StartupRequest) -> int:
        requests.append(request)
        return 0

    monkeypatch.setattr(cli, "_run_gui", fake_run_gui)
    return requests


def test_version_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == __version__


def test_gui_flag_cannot_be_combined_with_a_document() -> None:
    with pytest.raises(SystemExit) as error:
        cli.parse_cli(["--gui", "design.icproj"])

    assert error.value.code == 2


def test_release_diagnostic_cannot_be_combined_with_a_document(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as error:
        cli.parse_cli(["--release-diagnostic", "p", "r", str(tmp_path), "design.icproj"])

    assert error.value.code == 2


def test_no_document_starts_a_new_project(captured_gui: list[StartupRequest]) -> None:
    assert cli.main([]) == 0
    assert [request.kind for request in captured_gui] == [StartupKind.NEW]


def test_a_document_is_classified_before_the_gui_starts(
    tmp_path: Path, captured_gui: list[StartupRequest]
) -> None:
    document = tmp_path / "design.icproj"
    document.write_bytes(b"fixture")

    assert cli.main([str(document)]) == 0
    assert [request.path for request in captured_gui] == [document.resolve()]


def test_an_unsupported_document_exits_with_a_message(tmp_path: Path) -> None:
    document = tmp_path / "notes.txt"
    document.write_text("notes", encoding="utf-8")

    with pytest.raises(SystemExit, match="icc: .*icrules"):
        cli.main([str(document)])


class _FakeWindow:
    def __init__(self) -> None:
        self.opened: list[Path] = []
        self.shown = False

    def open_document(self, path: Path) -> None:
        self.opened.append(path)

    def show(self) -> None:
        self.shown = True


class _FakeDesktopApplication:
    """Stands in for the real QApplication so the launch wiring runs without Qt."""

    def __init__(self, pending: tuple[Path, ...] = ()) -> None:
        self._pending = pending
        self.connected: list[object] = []

    @property
    def file_open_requested(self) -> _FakeDesktopApplication:
        return self

    def connect(self, slot: object) -> None:
        self.connected.append(slot)

    def take_pending_open_paths(self) -> tuple[Path, ...]:
        return self._pending

    def exec(self) -> int:
        return 3


@pytest.fixture
def fake_gui(monkeypatch: pytest.MonkeyPatch) -> tuple[_FakeDesktopApplication, _FakeWindow]:
    from insulation_coordination.ui import app as app_module
    from insulation_coordination.ui import main_window as main_window_module

    application = _FakeDesktopApplication(pending=(Path("pending.icproj"),))
    window = _FakeWindow()
    monkeypatch.setattr(app_module, "DesktopApplication", _FakeDesktopApplication)
    monkeypatch.setattr(app_module, "create_application", lambda argv: application)
    monkeypatch.setattr(main_window_module, "MainWindow", lambda: window)
    return application, window


def test_the_gui_opens_the_startup_document_and_returns_the_exit_code(
    fake_gui: tuple[_FakeDesktopApplication, _FakeWindow],
) -> None:
    _, window = fake_gui

    exit_code = cli._run_gui(StartupRequest(StartupKind.PROJECT, Path("design.icproj")))

    assert exit_code == 3
    assert window.opened[0] == Path("design.icproj")
    assert window.shown is True


def test_the_gui_drains_the_paths_the_desktop_queued_before_startup(
    fake_gui: tuple[_FakeDesktopApplication, _FakeWindow],
) -> None:
    application, window = fake_gui

    cli._run_gui(StartupRequest(StartupKind.NEW))

    assert application.connected == [window.open_document]
    assert window.opened == [Path("pending.icproj")]


def test_a_plain_qapplication_skips_the_desktop_file_open_wiring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A QApplication another host created is not ours, so it carries no queued paths."""
    from insulation_coordination.ui import app as app_module
    from insulation_coordination.ui import main_window as main_window_module

    class _PlainApplication:
        def exec(self) -> int:
            return 0

    window = _FakeWindow()
    monkeypatch.setattr(app_module, "DesktopApplication", _FakeDesktopApplication)
    monkeypatch.setattr(app_module, "create_application", lambda argv: _PlainApplication())
    monkeypatch.setattr(main_window_module, "MainWindow", lambda: window)

    assert cli._run_gui(StartupRequest(StartupKind.NEW)) == 0
    assert window.opened == []


def test_release_diagnostic_writes_metadata_and_reports_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setattr(
        release_diagnostic,
        "run_release_diagnostic",
        lambda project, rules, out: _result(out, success=True),
    )

    exit_code = cli.main(["--release-diagnostic", "p.icproj", "r.icrules", str(output_dir)])

    metadata_path = output_dir / "release-diagnostic.json"
    assert exit_code == 0
    assert capsys.readouterr().out.strip() == str(metadata_path)
    assert json.loads(metadata_path.read_text(encoding="utf-8"))["success"] is True


def test_release_diagnostic_reports_a_failed_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        release_diagnostic,
        "run_release_diagnostic",
        lambda project, rules, out: _result(out, success=False),
    )

    exit_code = cli.main(["--release-diagnostic", "p.icproj", "r.icrules", str(tmp_path)])

    assert exit_code == 1
    assert json.loads((tmp_path / "release-diagnostic.json").read_text(encoding="utf-8"))[
        "success"
    ] is False


def test_release_diagnostic_reports_a_diagnostic_error_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(project: Path, rules: Path, out: Path) -> ReleaseDiagnosticResult:
        raise ReleaseDiagnosticError("rules package pin does not match")

    monkeypatch.setattr(release_diagnostic, "run_release_diagnostic", fail)

    exit_code = cli.main(["--release-diagnostic", "p.icproj", "r.icrules", str(tmp_path)])

    assert exit_code == 1
    assert "icc: rules package pin does not match" in capsys.readouterr().err


def test_release_diagnostic_reports_an_unwritable_output_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "absent" / "output"
    monkeypatch.setattr(
        release_diagnostic,
        "run_release_diagnostic",
        lambda project, rules, out: _result(out, success=True),
    )

    exit_code = cli.main(["--release-diagnostic", "p.icproj", "r.icrules", str(missing)])

    assert exit_code == 1
    assert "icc: " in capsys.readouterr().err
