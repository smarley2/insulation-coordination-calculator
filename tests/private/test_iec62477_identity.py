from pathlib import Path

import pytest

from insulation_coordination.rules.importer.identify import (
    UnsupportedStandardError,
    identify_standard,
)

pytestmark = pytest.mark.private_standard


def test_supplied_document_identifies_as_the_2022_edition(
    supplied_standards: dict[str, Path],
) -> None:
    identity = identify_standard(supplied_standards["iec62477-1-2022"])
    assert identity.standard == "IEC 62477-1"
    assert identity.edition == "2022"
    assert identity.recipe_id == "iec62477-1-2022"
    assert len(identity.sha256) == 64


def test_identity_is_stable_across_repeated_reads(
    supplied_standards: dict[str, Path],
) -> None:
    path = supplied_standards["iec62477-1-2022"]
    assert identify_standard(path).sha256 == identify_standard(path).sha256


def test_a_truncated_copy_is_refused(
    supplied_standards: dict[str, Path],
    tmp_path: Path,
) -> None:
    truncated = tmp_path / "truncated.pdf"
    truncated.write_bytes(supplied_standards["iec62477-1-2022"].read_bytes()[:4096])
    with pytest.raises(UnsupportedStandardError):
        identify_standard(truncated)
