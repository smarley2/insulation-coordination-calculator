from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from insulation_coordination.domain.rules import (
    RulePackage,
    SourceDocument,
    SourceGeometryReference,
    SourceReference,
)
from insulation_coordination.rules.validation import validate_rule_package


def test_source_reference_has_typed_document_and_page() -> None:
    source = SourceReference(
        document_id="synthetic-source",
        standard="SYNTHETIC",
        edition="1",
        page=7,
        clause="4.2",
    )

    assert source.page == 7
    assert source.note is None


def test_source_reference_rejects_page_zero() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        SourceReference(
            document_id="synthetic-source",
            standard="SYNTHETIC",
            edition="1",
            page=0,
        )


def test_source_geometry_rejects_invalid_sha_and_unordered_bbox() -> None:
    with pytest.raises(ValidationError, match="SHA-256"):
        SourceDocument(
            id="synthetic-source",
            standard="SYNTHETIC",
            edition="1",
            sha256="A" * 64,
        )
    with pytest.raises(ValidationError, match="SHA-256"):
        SourceGeometryReference(artifact_sha256="A" * 64)
    with pytest.raises(ValidationError, match="ordered"):
        SourceGeometryReference(
            artifact_sha256="a" * 64,
            bbox=(Decimal(2), Decimal(0), Decimal(1), Decimal(1)),
        )


def test_package_rejects_unknown_source_document_link(synthetic_package: RulePackage) -> None:
    package = synthetic_package
    bad = package.model_copy(
        update={
            "tables": (
                package.tables[0].model_copy(
                    update={
                        "source": package.tables[0].source.model_copy(
                            update={"document_id": "missing-source"}
                        )
                    }
                ),
                *package.tables[1:],
            )
        }
    )

    report = validate_rule_package(bad)

    assert "SOURCE_DOCUMENT_LINKS_VALID" in {
        item.code for item in report.results if not item.passed
    }


@pytest.mark.parametrize(
    ("field", "value"),
    (("standard", "SYNTHETIC-OTHER"), ("edition", "2")),
)
def test_package_rejects_source_document_standard_or_edition_mismatch(
    synthetic_package: RulePackage,
    field: str,
    value: str,
) -> None:
    package = synthetic_package
    bad = package.model_copy(
        update={
            "tables": (
                package.tables[0].model_copy(
                    update={"source": package.tables[0].source.model_copy(update={field: value})}
                ),
                *package.tables[1:],
            )
        }
    )

    report = validate_rule_package(bad)

    assert "SOURCE_DOCUMENT_LINKS_VALID" in {
        item.code for item in report.results if not item.passed
    }
