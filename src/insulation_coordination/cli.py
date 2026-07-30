import argparse
from collections.abc import Sequence

from insulation_coordination import __version__


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
    return 0
