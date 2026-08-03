from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def symlinks_allowed(tmp_path: Path) -> None:
    """Skip a symlink-rejection test on hosts that cannot create symlinks.

    Windows only allows this for administrators or with Developer Mode enabled,
    so the guarded behaviour is untestable rather than broken there.
    """
    probe = tmp_path / "symlink-probe"
    target = tmp_path / "symlink-probe-target"
    target.write_text("probe", encoding="utf-8")
    try:
        probe.symlink_to(target)
    except OSError as error:
        pytest.skip(f"symlinks cannot be created on this host: {error}")
    probe.unlink()
    target.unlink()
