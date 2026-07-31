from __future__ import annotations

import argparse
from collections.abc import Sequence

from insulation_coordination import __version__


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="icc")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--gui", action="store_true", help="Launch the desktop GUI")
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.gui:
        from insulation_coordination.ui.app import create_application
        from insulation_coordination.ui.main_window import MainWindow

        app = create_application(argv if argv is not None else [])
        window = MainWindow()
        window.show()
        return app.exec()
    return 0
