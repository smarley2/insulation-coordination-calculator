from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from insulation_coordination import __version__
from insulation_coordination.startup import StartupKind, StartupRequest, classify_startup_path


def parse_cli(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="icc")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--gui", action="store_true", help="Launch the desktop GUI")
    parser.add_argument("document", nargs="?", type=Path)
    args = parser.parse_args(argv)
    if args.gui and args.document is not None:
        parser.error("--gui cannot be combined with a document path")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_cli(argv)
    if args.version:
        print(__version__)
        return 0
    if args.document is None:
        request = StartupRequest(StartupKind.NEW)
    else:
        try:
            request = classify_startup_path(args.document)
        except (OSError, ValueError) as error:
            raise SystemExit(f"icc: {error}") from error
    return _run_gui(request)


def _run_gui(request: StartupRequest) -> int:
    from insulation_coordination.ui.app import DesktopApplication, create_application
    from insulation_coordination.ui.main_window import MainWindow

    app = create_application([])
    window = MainWindow()
    if request.path is not None:
        window.open_document(request.path)
    window.show()
    if isinstance(app, DesktopApplication):
        app.file_open_requested.connect(window.open_document)
        for path in app.take_pending_open_paths():
            window.open_document(path)
    return app.exec()
