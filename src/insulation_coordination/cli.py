from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from insulation_coordination import __version__
from insulation_coordination.startup import StartupKind, StartupRequest, classify_startup_path


def parse_cli(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="icc")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--gui", action="store_true", help="Launch the desktop GUI")
    parser.add_argument(
        "--release-diagnostic",
        nargs=3,
        metavar=("PROJECT", "RULES", "OUTPUT_DIR"),
        help="Run the packaged end-to-end release diagnostic",
    )
    parser.add_argument("document", nargs="?", type=Path)
    args = parser.parse_args(argv)
    if args.gui and (args.document is not None or args.release_diagnostic is not None):
        parser.error("--gui cannot be combined with a document or release diagnostic")
    if args.release_diagnostic is not None and args.document is not None:
        parser.error("--release-diagnostic cannot be combined with a document path")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_cli(argv)
    if args.version:
        print(__version__)
        return 0
    if args.release_diagnostic is not None:
        return _run_release_diagnostic(
            (
                Path(args.release_diagnostic[0]),
                Path(args.release_diagnostic[1]),
                Path(args.release_diagnostic[2]),
            )
        )
    if args.document is None:
        request = StartupRequest(StartupKind.NEW)
    else:
        try:
            request = classify_startup_path(args.document)
        except (OSError, ValueError) as error:
            raise SystemExit(f"icc: {error}") from error
    return _run_gui(request)


def _run_release_diagnostic(paths: tuple[Path, Path, Path]) -> int:
    from insulation_coordination.release_diagnostic import (
        ReleaseDiagnosticError,
        run_release_diagnostic,
    )

    project_path, rules_path, output_dir = paths
    try:
        result = run_release_diagnostic(project_path, rules_path, output_dir)
        metadata_path = output_dir / "release-diagnostic.json"
        metadata_path.write_text(
            json.dumps(result.model_dump(mode="json"), sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ReleaseDiagnosticError) as error:
        print(f"icc: {error}", file=sys.stderr)
        return 1
    print(metadata_path)
    return 0 if result.success else 1


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
