from pathlib import Path

import pytest

from insulation_coordination.startup import StartupKind, classify_startup_path


@pytest.mark.parametrize(
    ("name", "kind"),
    (("design.icproj", StartupKind.PROJECT), ("iec.icrules", StartupKind.RULES)),
)
def test_classify_startup_path_requires_existing_supported_file(
    tmp_path: Path, name: str, kind: StartupKind
) -> None:
    path = tmp_path / name
    path.write_bytes(b"fixture")

    request = classify_startup_path(path)

    assert request.kind is kind
    assert request.path == path.resolve()


def test_classify_startup_path_rejects_unknown_extension(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("notes", encoding="utf-8")

    with pytest.raises(ValueError, match=".icproj or .icrules"):
        classify_startup_path(path)
