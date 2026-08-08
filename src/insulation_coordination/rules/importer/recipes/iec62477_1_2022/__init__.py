"""IEC 62477-1:2022 extraction recipe. Layout facts only."""

from insulation_coordination.rules.importer.identify import StandardRecipe
from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import (
    clauses,
    identity,
    tables,
)

RECIPE = StandardRecipe(
    id="iec62477-1-2022",
    standard="IEC 62477-1",
    edition="2022",
    identity_claim_pattern=identity.IDENTITY_CLAIM_PATTERN,
    expected_page_count=identity.EXPECTED_PAGE_COUNT,
    metadata_identity_fields=identity.METADATA_IDENTITY_FIELDS,
    metadata_identity_anchors=identity.METADATA_IDENTITY_ANCHORS,
    identity_anchors=identity.IDENTITY_ANCHORS,
    tables=tables.TABLES,
    formulas=tables.FORMULAS,
    mappings=(),
    clauses=clauses.CLAUSES,
)

__all__ = ["RECIPE"]
