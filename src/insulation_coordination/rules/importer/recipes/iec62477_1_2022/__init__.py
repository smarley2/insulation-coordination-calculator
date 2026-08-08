"""IEC 62477-1:2022 extraction recipe. Layout facts only."""

from insulation_coordination.rules.importer.identify import StandardRecipe
from insulation_coordination.rules.importer.iec62477_2022 import semantic_ids as ids
from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import (
    clauses,
    curves,
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
    curves=curves.CURVES,
    required_curves=(ids.DVC_FAULT_TIME_VOLTAGE,),
)

__all__ = ["RECIPE"]
