from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from insulation_coordination.domain.project import FrozenModel
from insulation_coordination.domain.rules import (
    CurveInterpolation,
    CurveSegmentType,
    FaultTimeVoltageSelector,
    Identifier,
    NotesText,
    ReferenceText,
    RuleKind,
    SourceReference,
)

LOGGER = logging.getLogger(__name__)
MAX_STANDARD_PDF_BYTES = 128 * 1024 * 1024
MAX_IDENTITY_PAGES = 20


class StandardIdentificationError(ValueError):
    """A PDF cannot be identified safely."""


class UnsupportedStandardError(StandardIdentificationError):
    """The PDF is not one of the explicitly supported editions."""


class UnsupportedEditionError(UnsupportedStandardError):
    """The PDF is a supported standard, but not the supported edition."""

    def __init__(self, standard: str, edition: str) -> None:
        self.detected_standard = standard
        self.detected_edition = edition
        super().__init__(
            f"{standard} edition {edition} is not supported; this build supports one edition "
            "per standard and will not mix editions"
        )


class PasswordRequiredError(StandardIdentificationError):
    """The PDF could not be unlocked with the available password."""

    def __init__(self, path: Path, *, supplied: bool = False) -> None:
        self.path = path
        message = (
            "could not unlock encrypted standard PDF with the supplied password"
            if supplied
            else "encrypted standard PDF requires a password"
        )
        super().__init__(f"{message}: {path.name}")


class AmbiguousStandardError(StandardIdentificationError):
    """More than one recipe matched the PDF."""


class StandardIdentity(FrozenModel):
    standard: Identifier
    edition: Identifier
    sha256: str = Field(pattern=r"[0-9a-f]{64}")
    page_count: int = Field(ge=1)
    recipe_id: Identifier


class TableSegmentSpec(FrozenModel):
    id: Identifier
    page_number: int = Field(ge=1)
    title_anchor: ReferenceText
    expected_raw_rows: int = Field(ge=1)
    expected_raw_columns: int = Field(ge=1)
    expected_bbox: tuple[float, float, float, float]
    bbox_tolerance: float = Field(default=1.0, ge=0, le=200)
    anchor_max_vertical_gap: float = Field(default=80.0, ge=0, le=300)
    anchor_min_x_overlap: float = Field(default=0.1, ge=0, le=1)
    logical_row_offset: int = Field(default=0, ge=0)
    source_columns: tuple[int, ...] = ()
    header_rows: tuple[int, ...] = ()
    data_rows: tuple[int, ...] = ()
    note_rows: tuple[int, ...] = ()
    footnote_rows: tuple[int, ...] = ()
    context_cells: tuple[tuple[int, int], ...] = ()
    page_search_radius: int = Field(default=0, ge=0, le=5)
    #: How row boundaries are found. ``"lines"`` uses the ruling lines the page draws,
    #: which is right for tables whose every logical row has its own rule. ``"text"``
    #: takes one row per text line, which is what a table needs when several logical rows
    #: share one ruled cell; without it those rows would arrive stacked inside one cell.
    row_strategy: Literal["lines", "text"] = "lines"


class CompoundQuantitySpec(FrozenModel):
    component_ids: tuple[Identifier, ...] = Field(min_length=1)
    formula_candidates: tuple[tuple[Identifier, Identifier | None], ...] = ()
    allowed_formula_ids: tuple[tuple[Identifier, Identifier], ...] = ()

    @model_validator(mode="after")
    def _valid_component_contract(self) -> CompoundQuantitySpec:
        if len(self.component_ids) != len(set(self.component_ids)):
            raise ValueError("compound component IDs must be unique")
        unknown = {
            component_id
            for component_id, _formula_id in (
                *self.formula_candidates,
                *self.allowed_formula_ids,
            )
            if component_id not in self.component_ids
        }
        if unknown:
            raise ValueError("formula candidate refers to an undeclared compound component")
        allowed = set(self.allowed_formula_ids) or {
            (component_id, formula_id)
            for component_id, formula_id in self.formula_candidates
            if formula_id is not None
        }
        if any(
            formula_id is not None and (component_id, formula_id) not in allowed
            for component_id, formula_id in self.formula_candidates
        ):
            raise ValueError("formula candidate is outside its component route")
        if any(
            formula_id is None
            and not any(
                allowed_component_id == component_id
                for allowed_component_id, _allowed_formula_id in allowed
            )
            for component_id, formula_id in self.formula_candidates
        ):
            raise ValueError("zero formula candidates need a component-local allowed formula")
        return self


class TableColumnSpec(FrozenModel):
    semantic_id: Identifier
    heading: ReferenceText
    source_column: int = Field(ge=0)
    role: Literal["axis", "data", "context"]
    unit: Identifier
    axis_value: Decimal | None = None
    #: This column's axis value is the number found in this row of its own header,
    #: instead of a value declared in the recipe. Use this for axis values that come
    #: from a licensed table's own header row rather than a value safe to hardcode.
    axis_value_source_row: int | None = Field(default=None, ge=0)
    fill_down: bool = False
    compound_quantity: CompoundQuantitySpec | None = None
    projected_component_id: Identifier | None = None

    @model_validator(mode="after")
    def _valid_projected_component(self) -> TableColumnSpec:
        if self.projected_component_id is not None and (
            self.compound_quantity is None
            or self.projected_component_id not in self.compound_quantity.component_ids
        ):
            raise ValueError("projected component must belong to the compound quantity")
        if self.compound_quantity is not None and self.role != "data":
            raise ValueError("only data columns may declare compound quantities")
        return self


BlankCellSemantics = Literal[
    "inherit",
    "not_applicable",
    "reference",
    "structural",
    "missing",
]


class MergedCellSpec(FrozenModel):
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    inherit: Literal["right", "down", "both", "none"]


class BlankCellSpec(FrozenModel):
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    semantics: BlankCellSemantics


class ReferenceSlotSpec(FrozenModel):
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    target_rule_id: Identifier
    target_kind: RuleKind


class TokenGrammarSpec(FrozenModel):
    """A reviewed neutral-token grammar for non-numeric data cells.

    Maps normalized token text extracted from a data cell onto a typed value.
    Prefix matching supports source cells that append reviewed footnote markers
    or qualifiers to a neutral category. Extraction never guesses an unknown
    token; it checks that every data-cell token belongs to the grammar.
    """

    target: Literal["boolean", "categorical"]
    tokens: tuple[tuple[Identifier, bool | Identifier], ...] = Field(min_length=2)
    match: Literal["exact", "prefix"] = "exact"

    @model_validator(mode="after")
    def _unique_tokens(self) -> TokenGrammarSpec:
        texts = tuple(text for text, _value in self.tokens)
        if len(texts) != len(set(texts)):
            raise ValueError("token grammar must not repeat a token")
        if self.target == "boolean" and any(type(value) is not bool for _, value in self.tokens):
            raise ValueError("boolean token grammar values must be booleans")
        if self.target == "categorical" and any(
            not isinstance(value, str) for _, value in self.tokens
        ):
            raise ValueError("categorical token grammar values must be identifiers")
        return self

    def resolve(self, raw_text: str) -> bool | Identifier | None:
        """The typed value for one extracted token, or None when unknown."""

        normalized = _normalized(raw_text)
        for text, value in self.tokens:
            candidate = _normalized(text)
            if candidate == normalized or (
                self.match == "prefix" and normalized.startswith(candidate)
            ):
                return value
        return None


class TableAuditSpec(FrozenModel):
    semantic_id: Identifier
    source_table: ReferenceText
    title_anchor: ReferenceText
    page_number: int = Field(ge=1)
    clause: ReferenceText
    target_unit: Identifier
    expected_raw_rows: int = Field(ge=1)
    expected_raw_columns: int = Field(ge=1)
    expected_bbox: tuple[float, float, float, float]
    bbox_tolerance: float = Field(default=1.0, ge=0, le=200)
    anchor_max_vertical_gap: float = Field(default=80.0, ge=0, le=300)
    anchor_min_x_overlap: float = Field(default=0.1, ge=0, le=1)
    data_strategy: Literal["rectangle", "numeric_row_major"]
    data_row_start: int | None = Field(default=None, ge=0)
    data_column_start: int | None = Field(default=None, ge=0)
    expected_data_rows: int = Field(ge=1)
    expected_data_columns: int = Field(ge=1)
    row_axis_id: Identifier
    row_axis_unit: Identifier
    column_axis_id: Identifier
    column_axis_unit: Identifier
    allowed_suffixes: tuple[str, ...] = ()
    allowed_qualifiers: tuple[Literal["up_to"], ...] = ()
    assertions: tuple[
        Literal[
            "complete_grid",
            "strictly_increasing_axes",
            "raw_value_correspondence",
        ],
        ...,
    ]
    segments: tuple[TableSegmentSpec, ...] = ()
    columns: tuple[TableColumnSpec, ...] = ()
    merged_cells: tuple[MergedCellSpec, ...] = ()
    blank_cells: tuple[BlankCellSpec, ...] = ()
    reference_slots: tuple[ReferenceSlotSpec, ...] = ()
    token_grammar: TokenGrammarSpec | None = None
    page_search_radius: int = Field(default=0, ge=0, le=5)
    interpolation: Literal["none", "linear"] = "none"
    #: Decision rule IDs this table projects to instead of a ``Table``. Declared on the
    #: spec so completeness reporting reads the routes from the recipe rather than from a
    #: table of standard-specific identifiers inside generic review code.
    decision_route_ids: tuple[Identifier, ...] = ()
    #: This grid is extracted as evidence for a cross-standard comparison, not as an
    #: executable rule, so review does not project it. A standard that reproduces another's
    #: table needs the numbers present to prove or refute equivalence, while the rule the
    #: calculator executes stays the one already approved from the other standard.
    comparison_only: bool = False
    #: This grid's data cells are reviewed text, not quantities: the source states a
    #: procedure as a table of subjects and conditions. Its cells are therefore not flagged
    #: for numeric retyping -- there is no number to retype -- and the rule projected from
    #: the grid is what a maintainer reviews, exactly as a clause fragment's projected rule
    #: is. Only the projection understands which row means what, so a spec that sets this
    #: must also register a grid projector.
    text_field_table: bool = False

    @model_validator(mode="after")
    def _comparison_only_projects_nothing(self) -> TableAuditSpec:
        if self.comparison_only and self.decision_route_ids:
            raise ValueError("a comparison-only table cannot declare decision routes")
        if self.comparison_only and self.text_field_table:
            raise ValueError("a table is either comparison evidence or a text field table")
        return self

    @model_validator(mode="after")
    def _axis_value_source_row_is_a_declared_header_row(self) -> TableAuditSpec:
        """A column's declared axis-value row must be one extraction will mark as a

        header, in segment-local numbering -- the same space ``header_rows`` already
        uses. Otherwise the row could resolve to a data cell at runtime instead of
        raising, silently feeding a data value into the column axis.
        """
        for column in self.columns:
            if column.axis_value_source_row is None:
                continue
            if not any(
                column.axis_value_source_row in segment.header_rows for segment in self.segments
            ):
                raise ValueError(
                    f"column {column.semantic_id!r} axis_value_source_row "
                    f"{column.axis_value_source_row} is not declared in any segment's "
                    "header_rows"
                )
        return self

    @model_validator(mode="after")
    def _structural_coordinates_fit_the_raw_grid(self) -> TableAuditSpec:
        blank_coordinates = tuple((item.row, item.column) for item in self.blank_cells)
        reference_coordinates = tuple((item.row, item.column) for item in self.reference_slots)
        merge_anchors = tuple((item.row, item.column) for item in self.merged_cells)
        for label, coordinates in (
            ("blank", blank_coordinates),
            ("reference", reference_coordinates),
            ("merged", merge_anchors),
        ):
            if len(coordinates) != len(set(coordinates)):
                raise ValueError(f"table has duplicate {label} cell coordinates")
            if any(
                row >= self.expected_raw_rows or column >= self.expected_raw_columns
                for row, column in coordinates
            ):
                raise ValueError(f"table {label} cell is outside the raw grid")
        if any(
            merge.row + merge.row_span > self.expected_raw_rows
            or merge.column + merge.column_span > self.expected_raw_columns
            for merge in self.merged_cells
        ):
            raise ValueError("table merged cell span is outside the raw grid")
        return self


class EquationAuditSpec(FrozenModel):
    semantic_id: Identifier
    unit: Identifier
    variables: tuple[Identifier, ...]
    expression_shape: ReferenceText
    page_number: int = Field(ge=1)
    clause: ReferenceText
    table: ReferenceText | None = None
    figure: ReferenceText | None = None
    rendered_anchor: ReferenceText | None = None
    applicability: ReferenceText = "review required"
    extract_from_pdf: bool = False
    expected_bbox: tuple[float, float, float, float] | None = None


FormulaAuditSpec = EquationAuditSpec


class MappingAuditSpec(FrozenModel):
    id: Identifier
    semantic_route: Identifier
    target_rule_id: Identifier
    family: Identifier
    page_number: int = Field(ge=1)
    clause: ReferenceText
    table: ReferenceText | None = None
    figure: ReferenceText | None = None


class CrossStandardCheckSpec(FrozenModel):
    """One declared equivalence claim between two grids, and the cells that prove it.

    IEC 62477-1 reproduces spacing requirements the approved IEC 60664 rules already
    carry. A check names the cells whose agreement would justify a compatibility mapping;
    ``rules.importer.crosscheck`` performs the comparison.
    """

    id: Identifier
    #: The route the resulting mapping records, and the rule it resolves to -- the same
    #: shape ``MappingAuditSpec`` declares, not the raw grids compared to prove the claim.
    #: The source is a semantic route of this standard, unique per check; the target is the
    #: already-approved formula of the other standard that satisfies it, and several checks
    #: may share one target.
    source_rule_id: Identifier
    target_rule_id: Identifier
    #: The raw grids whose cells prove the claim. They live in the draft as evidence and
    #: never enter the approved package.
    source_grid_id: Identifier
    target_grid_id: Identifier
    family: Identifier
    #: ``(source cell id, target cell id)`` pairs, where a cell id is
    #: ``"<logical_row>/<logical_column>"`` as the raw grid records data cells.
    cell_map: tuple[tuple[Identifier, Identifier], ...]
    #: Every data cell the source grid contains. Declared apart from ``cell_map`` so a
    #: partial map cannot compare a subset of a table and still claim the whole table is
    #: equivalent.
    source_data_cell_ids: tuple[Identifier, ...]
    #: Cell texts that mean "this cell carries no requirement". Two printings of the same
    #: requirement may mark an inapplicable cell differently -- one leaves it empty, the
    #: other prints a marker -- and that is a notation difference, not a difference in
    #: requirement. Declaring the markers keeps the equivalence explicit: any other
    #: unparsed text still counts as a divergence, so a cell reading "see another clause"
    #: is never quietly equated with an empty one.
    no_requirement_tokens: tuple[str, ...] = ()
    source: SourceReference
    notes: NotesText = ""

    @model_validator(mode="after")
    def _map_covers_every_source_data_cell(self) -> CrossStandardCheckSpec:
        mapped = tuple(source_id for source_id, _target_id in self.cell_map)
        if len(mapped) != len(set(mapped)):
            raise ValueError("cross-standard cell map must not repeat a source cell")
        if set(mapped) != set(self.source_data_cell_ids):
            raise ValueError("cross-standard cell map must cover every source data cell")
        if len(self.source_data_cell_ids) != len(set(self.source_data_cell_ids)):
            raise ValueError("cross-standard source data cell IDs must be unique")
        return self


class ClauseAuditSpec(FrozenModel):
    """Structural contract for one reviewed clause fragment.

    Layout facts only: page, bbox, root shape, and output kind. The recipe never
    stores clause wording; extracted text stays in private raw fragments.
    """

    semantic_id: Identifier
    clause: ReferenceText
    page_number: int = Field(ge=1)
    expected_bbox: tuple[float, float, float, float]
    expected_root_kind: Literal["paragraph", "bullets"]
    output_kind: Literal["decision", "procedure"]
    #: Rules this clause projects to beyond one carrying the spec's own identifier -- for
    #: example the guidance a source NOTE becomes. Declared so a projected route inherits
    #: this clause's review inventory and source artifact, while an unrelated rule that
    #: merely starts with the same identifier does not.
    projected_rule_ids: tuple[Identifier, ...] = ()


class CurveAuditSpec(FrozenModel):
    """Structural contract for one reviewed source figure.

    Layout facts only: figure number, page, bbox, axis kinds/units/scales, and the
    permitted variant/segment vocabulary. No curve coordinates or labels live here.
    """

    semantic_id: Identifier
    figure: ReferenceText
    page_number: int = Field(ge=1)
    expected_bbox: tuple[float, float, float, float]
    expected_pixel_size: tuple[int, int] | None = None
    x_quantity_kind: Identifier
    x_unit: Identifier
    y_quantity_kind: Identifier
    y_unit: Identifier
    x_scale: Literal["log10"]
    y_scale: Literal["log10"]
    x_source_unit: Identifier | None = None
    variant_slots: tuple[FaultTimeVoltageSelector, ...] = Field(min_length=1)
    permitted_segment_types: tuple[CurveSegmentType, ...] = Field(min_length=1)
    permitted_interpolations: tuple[CurveInterpolation, ...] = Field(min_length=1)


#: A recipe-declared projection from one reviewed raw artifact to typed rules, returning
#: the projected rules and their semantic proposals. The artifact and rule types stay
#: unannotated here on purpose: ``extract.py`` and ``clauses.py`` both import this module,
#: so naming their models would close an import cycle. The recipe modules that register a
#: projector carry the precise signatures.
type GridProjector = Callable[[Any, StandardIdentity], tuple[tuple[Any, ...], tuple[Any, ...]]]
#: A clause projection additionally receives the reviewed draft the fragment came from. A
#: source that states one requirement in several places -- a procedure whose classification
#: only the test cross-reference matrix carries, a preconditioning requirement stated in two
#: clauses and a table row -- cannot be projected from one fragment alone, and reading the
#: sibling artifacts from the draft keeps that cross-reading inside the projection instead of
#: spreading a second mechanism across review.
type ClauseProjector = Callable[
    [Any, StandardIdentity, Any], tuple[tuple[Any, ...], tuple[Any, ...]]
]


class StandardRecipe(FrozenModel):
    id: Identifier
    standard: Identifier
    edition: Identifier
    identity_claim_pattern: str
    expected_page_count: int = Field(ge=1)
    accepted_page_counts: tuple[int, ...] = ()
    page_number_offsets: tuple[tuple[int, int], ...] = ()
    metadata_identity_fields: tuple[str, ...]
    metadata_identity_anchors: tuple[str, ...]
    identity_anchors: tuple[str, ...]
    tables: tuple[TableAuditSpec, ...]
    formulas: tuple[FormulaAuditSpec, ...]
    mappings: tuple[MappingAuditSpec, ...]
    clauses: tuple[ClauseAuditSpec, ...] = ()
    curves: tuple[CurveAuditSpec, ...] = ()
    #: Curve semantics the recipe's standard requires. A draft missing a reviewed
    #: curve rule for one of these cannot approve. Declared here so approval does
    #: not hard-code any one standard's curve IDs.
    required_curves: tuple[Identifier, ...] = ()
    #: Projections keyed by the semantic ID of the spec they consume. Declared here so
    #: generic review code dispatches by lookup instead of branching on one standard's
    #: identifiers. A table without an entry projects through ``project_table``.
    grid_projectors: Mapping[Identifier, GridProjector] = {}
    clause_projectors: Mapping[Identifier, ClauseProjector] = {}
    #: Equivalence claims against rules from another standard in the same package. A claim
    #: either proves out and yields a compatibility mapping or blocks approval.
    cross_standard_checks: tuple[CrossStandardCheckSpec, ...] = ()

    @model_validator(mode="after")
    def _projectors_match_declared_specs(self) -> StandardRecipe:
        table_ids = {spec.semantic_id for spec in self.tables}
        clause_ids = {spec.semantic_id for spec in self.clauses}
        if set(self.grid_projectors) - table_ids:
            raise ValueError("grid projector refers to an undeclared table spec")
        if set(self.clause_projectors) != clause_ids:
            raise ValueError("every clause spec needs exactly one projector")
        for spec in self.tables:
            if spec.semantic_id in self.grid_projectors:
                continue
            # Only a projection understands which reviewed text cell means what, so a text
            # field table without one yields nothing. The registry lives here rather than on
            # the spec, so the spec cannot check this itself -- but the recipe author is
            # still stopped when the recipe is constructed instead of when a gate reads it.
            if spec.text_field_table:
                raise ValueError("a text field table needs a grid projector to read its cells")
            if spec.decision_route_ids:
                raise ValueError("a table projecting decisions needs a grid projector")
        return self

    def matches_text(self, text: str) -> bool:
        return all(_normalized(anchor) in text for anchor in self.identity_anchors)

    def detected_claims(
        self, *, first_page_text: str, metadata: dict[str, str]
    ) -> set[tuple[str, str]]:
        """Every (standard, edition) pair this recipe's pattern finds in the document.

        The standard is normalized because PDF text extraction produces irregular
        whitespace: a document rendering "IEC  60664-1" would otherwise never equal the
        recipe's own name, and the document would be rejected as unrecognized.
        """
        return {
            (_normalized(standard), edition)
            for value in (*metadata.values(), first_page_text)
            for standard, edition in re.findall(self.identity_claim_pattern, value)
        }

    def matches_identity(
        self,
        *,
        text: str,
        first_page_text: str,
        metadata: dict[str, str],
        page_count: int,
    ) -> bool:
        metadata_text = _normalized(
            " ".join(metadata.get(field, "") for field in self.metadata_identity_fields)
        )
        identifying_claims = self.detected_claims(
            first_page_text=first_page_text, metadata=metadata
        )
        if identifying_claims - {(_normalized(self.standard), self.edition)}:
            return False
        metadata_identifies_document = all(
            _normalized(anchor) in metadata_text for anchor in self.metadata_identity_anchors
        )
        return (
            metadata_identifies_document
            or page_count in (self.expected_page_count, *self.accepted_page_counts)
        ) and self.matches_text(text)


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _read_pdf(
    path: Path,
    password: str | None = None,
) -> tuple[PdfReader, str, str, str, dict[str, str]]:
    try:
        size = path.stat().st_size
        if size <= 0 or size > MAX_STANDARD_PDF_BYTES:
            raise UnsupportedStandardError("standard PDF has an invalid or excessive size")
        payload = path.read_bytes()
        if not payload.startswith(b"%PDF-"):
            raise UnsupportedStandardError("standard source is not a PDF")
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(password or ""):
            raise PasswordRequiredError(path, supplied=password is not None)
        if not reader.pages:
            raise UnsupportedStandardError("standard PDF has no pages")
        page_texts = tuple(page.extract_text() or "" for page in reader.pages[:MAX_IDENTITY_PAGES])
        text = "\n".join(page_texts)
        metadata = {
            str(key): str(value)
            for key, value in (reader.metadata or {}).items()
            if value is not None
        }
        return (
            reader,
            hashlib.sha256(payload).hexdigest(),
            _normalized(text),
            _normalized(page_texts[0]),
            metadata,
        )
    except StandardIdentificationError:
        raise
    # A malformed font, page tree, or object reference surfaces from the PDF layer as a
    # missing key or index rather than a PyPdfError. Identification is the gate in front
    # of a file the maintainer picked, so it refuses the document instead of letting the
    # PDF layer's own error escape.
    except (OSError, EOFError, PyPdfError, TypeError, ValueError, LookupError) as error:
        raise UnsupportedStandardError("standard PDF could not be read") from error


def identify_standard(path: Path, password: str | None = None) -> StandardIdentity:
    """Identify one supported edition without trusting the filename."""

    reader, digest, text, first_page_text, metadata = _read_pdf(path, password=password)
    # Imported lazily to avoid recipe registration during module initialization.
    from insulation_coordination.rules.importer.recipes import RECIPES

    text_matches = tuple(recipe for recipe in RECIPES if recipe.matches_text(text))
    if len(text_matches) > 1:
        raise AmbiguousStandardError("PDF matches more than one supported standard recipe")
    matches = tuple(
        recipe
        for recipe in RECIPES
        if recipe.matches_identity(
            text=text,
            first_page_text=first_page_text,
            metadata=metadata,
            page_count=len(reader.pages),
        )
    )
    if not matches:
        for recipe in RECIPES:
            for standard, edition in recipe.detected_claims(
                first_page_text=first_page_text,
                metadata=metadata,
            ):
                if standard == _normalized(recipe.standard) and edition != recipe.edition:
                    raise UnsupportedEditionError(recipe.standard, edition)
        raise UnsupportedStandardError("PDF is not a recognized supported IEC edition")
    if len(matches) != 1:
        raise AmbiguousStandardError("PDF matches more than one supported standard recipe")
    recipe = matches[0]
    LOGGER.info(
        "recognized standard recipe=%s pages=%d",
        recipe.id,
        len(reader.pages),
    )
    return StandardIdentity(
        standard=recipe.standard,
        edition=recipe.edition,
        sha256=digest,
        page_count=len(reader.pages),
        recipe_id=recipe.id,
    )
