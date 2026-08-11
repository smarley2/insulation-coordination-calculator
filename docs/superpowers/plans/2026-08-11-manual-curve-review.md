# Manual Curve Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace automatic IEC curve reconstruction with deterministic manual calibration, point entry, visual handles, exact review, and deletion of obsolete OCR/tracing/proof code.

**Architecture:** Import retains only verified source-figure identity and rendering metadata. A focused manual-curve service converts reviewed log-plot coordinates into existing `PiecewiseCurveRule` variants, while Rule Manager provides a synchronized point table and draggable overlay. Final package curve models and evaluator stay unchanged, preserving approved `.icrules` compatibility.

**Tech Stack:** Python 3.12, PySide6, Pydantic, `Decimal`, pypdf, pdfplumber, pytest/pytest-qt.

## Global Constraints

- Do not add dependencies.
- Use `Decimal`; never derive package values through binary floating-point arithmetic.
- Public code, tests, fixtures, docs, commits, and PR text contain no licensed labels, values, coordinates, screenshots, PDFs, reconstructed curves, or private digests.
- Public tests use synthetic figures and values only.
- Manual review is authoritative; UI must not claim machine-proven conservatism.
- Keep `PiecewiseCurveRule`, `FaultTimeVoltageVariant`, `CurvePoint`, `CurveSegment`, archive schema, evaluator behavior, and existing approved-package loading compatible.
- Keep source PDF pixels local and out of draft/package serialization.
- Preserve exact typed selector matching and refuse extrapolation.
- Run repository commands with `uv`; use parallel pytest except while debugging one test.

---

## File map

- `src/insulation_coordination/rules/importer/curves.py`: source-figure metadata, manual plot calibration, log coordinate conversion, and source-only extraction.
- `src/insulation_coordination/rules/importer/extract.py`: draft-only manual calibration/review state and source-only curve import.
- `src/insulation_coordination/rules/importer/review.py`: atomic calibration, point replacement, segment inference, and manual variant review.
- `src/insulation_coordination/rules/importer/approval.py`: exact manual-review approval gate and content audit.
- `src/insulation_coordination/ui/curve_review.py`: semantic labels, source viewer, calibration controls, point table, handles, and review actions.
- `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/projection.py`: aggregate final variants in recipe order without extracting geometry.
- `tests/rules/test_manual_curve_review.py`: pure calibration, mutation, audit, and approval tests.
- `tests/ui/test_curve_review.py`: rewritten focused model/dialog tests.
- `tests/rules/test_curve_source_extraction.py`: retained source-location/hash tests, stripped of OCR/trace expectations.
- `tests/rules/importer/iec62477_2022/test_figure_curve_proposals.py`: source-only import and manual projection tests.
- `tests/private/test_iec62477_curves.py`: structural manual-review integration only.
- `AGENTS.md`: remove obsolete Tesseract setup and automatic digitization timing guidance after measured verification.

### Task 1: Manual plot calibration and coordinate conversion

**Files:**
- Modify: `src/insulation_coordination/rules/importer/curves.py:54-237`
- Create: `tests/rules/test_manual_curve_review.py`

**Interfaces:**
- Consumes: existing `FrozenModel`, `CurvePoint`, `Decimal`.
- Produces: `ManualPlotCalibration`, `pixel_to_source_point(...)`, `source_point_to_pixel(...)`, `infer_curve_segments(...)`.

- [ ] **Step 1: Write failing calibration and segment tests**

```python
from decimal import Decimal

from insulation_coordination.domain.rules import CurvePoint
from insulation_coordination.rules.importer.curves import (
    ManualPlotCalibration,
    infer_curve_segments,
    pixel_to_source_point,
    source_point_to_pixel,
)


def _calibration() -> ManualPlotCalibration:
    return ManualPlotCalibration(
        figure_artifact_sha256="0" * 64,
        left=Decimal("20"),
        top=Decimal("10"),
        right=Decimal("320"),
        bottom=Decimal("210"),
        x_min=Decimal("1"),
        x_max=Decimal("1000"),
        y_min=Decimal("1"),
        y_max=Decimal("100"),
    )


def test_manual_log_calibration_round_trips_without_float() -> None:
    calibration = _calibration()
    point = pixel_to_source_point(Decimal("120"), Decimal("110"), calibration)

    assert point.x == Decimal("10")
    assert point.y == Decimal("10")
    assert source_point_to_pixel(point, calibration) == (
        Decimal("120"),
        Decimal("110"),
    )


def test_segments_are_inferred_from_adjacent_y_values() -> None:
    points = (
        CurvePoint(x=Decimal("1"), y=Decimal("100")),
        CurvePoint(x=Decimal("10"), y=Decimal("100")),
        CurvePoint(x=Decimal("100"), y=Decimal("20")),
        CurvePoint(x=Decimal("1000"), y=Decimal("20")),
    )

    assert tuple(
        (segment.start, segment.end, segment.segment_type, segment.interpolation)
        for segment in infer_curve_segments(points)
    ) == (
        (0, 1, "plateau", "constant"),
        (1, 2, "continuous", "log_log"),
        (2, 3, "plateau", "constant"),
    )
```

- [ ] **Step 2: Run tests and confirm missing-interface failure**

Run: `uv run pytest tests/rules/test_manual_curve_review.py -q`

Expected: collection fails because `ManualPlotCalibration` and conversion helpers do not exist.

- [ ] **Step 3: Add minimal validated calibration and pure helpers**

```python
class ManualPlotCalibration(FrozenModel):
    figure_artifact_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    left: Decimal
    top: Decimal
    right: Decimal
    bottom: Decimal
    x_min: Decimal
    x_max: Decimal
    y_min: Decimal
    y_max: Decimal

    @model_validator(mode="after")
    def _valid_bounds(self) -> Self:
        values = (
            self.left, self.top, self.right, self.bottom,
            self.x_min, self.x_max, self.y_min, self.y_max,
        )
        if any(not value.is_finite() for value in values):
            raise ValueError("manual curve calibration values must be finite")
        if self.left >= self.right or self.top >= self.bottom:
            raise ValueError("manual curve plot rectangle must be ordered")
        if self.x_min <= 0 or self.y_min <= 0:
            raise ValueError("manual log-axis bounds must be positive")
        if self.x_min >= self.x_max or self.y_min >= self.y_max:
            raise ValueError("manual curve axis bounds must be ordered")
        return self
```

Implement both transforms with `Decimal.log10()` and exponentiation through the repository's existing Decimal pattern. Clamp only UI drag positions; pure conversion rejects points outside the rectangle. Implement `infer_curve_segments` with one adjacent-pair pass.

- [ ] **Step 4: Add invalid-bound and outside-rectangle tests**

```python
@pytest.mark.parametrize(
    ("field", "value"),
    (("right", "20"), ("bottom", "10"), ("x_min", "0"), ("y_max", "1")),
)
def test_manual_calibration_rejects_invalid_bounds(field: str, value: str) -> None:
    payload = _calibration().model_dump(mode="python")
    payload[field] = Decimal(value)
    with pytest.raises(ValueError):
        ManualPlotCalibration.model_validate(payload)


def test_pixel_conversion_rejects_point_outside_plot() -> None:
    with pytest.raises(ValueError, match="outside reviewed plot rectangle"):
        pixel_to_source_point(Decimal("19"), Decimal("110"), _calibration())
```

- [ ] **Step 5: Run focused tests**

Run: `uv run pytest tests/rules/test_manual_curve_review.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/rules/importer/curves.py tests/rules/test_manual_curve_review.py
git commit -m "feat: add manual curve calibration"
```

### Task 2: Draft evidence and atomic manual variant replacement

**Files:**
- Modify: `src/insulation_coordination/rules/importer/extract.py:165-198,510-590`
- Modify: `src/insulation_coordination/rules/importer/review.py:1708-2859`
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/projection.py:463-533`
- Test: `tests/rules/test_manual_curve_review.py`

**Interfaces:**
- Consumes: Task 1 `ManualPlotCalibration`, `infer_curve_segments`, existing recipe `variant_slots`.
- Produces: `CurveCalibrationReview`, extended `CurveVariantReview`, `set_manual_curve_calibration(...)`, `replace_manual_curve_variant(...)`, `review_curve_variant(...)` without proof dependencies.

- [ ] **Step 1: Write failing tests for exact IDs, labels-independent ordering, and atomic replacement**

```python
def test_manual_variant_replacement_uses_recipe_slot_identity(synthetic_curve_draft) -> None:
    calibrated = set_manual_curve_calibration(
        synthetic_curve_draft,
        figure="5",
        calibration=_calibration(),
        actor="Reviewer",
        notes="Marked synthetic plot rectangle.",
    )
    changed = replace_manual_curve_variant(
        calibrated,
        variant_id="synthetic.curve.5.1",
        source_points=(
            CurvePoint(x=Decimal("1"), y=Decimal("100")),
            CurvePoint(x=Decimal("10"), y=Decimal("100")),
            CurvePoint(x=Decimal("100"), y=Decimal("20")),
            CurvePoint(x=Decimal("1000"), y=Decimal("20")),
        ),
        actor="Reviewer",
        notes="Entered synthetic curve points.",
        input_origin="empty",
    )

    variant = next(v for rule in changed.curves for v in rule.variants)
    assert variant.id == "synthetic.curve.5.1"
    assert tuple(segment.interpolation for segment in variant.segments) == (
        "constant", "log_log", "constant"
    )
    assert not changed.curve_variant_reviews
```

Use a synthetic `StandardRecipe` monkeypatch; never use IEC values or source labels.

- [ ] **Step 2: Run test and confirm missing-function failure**

Run: `uv run pytest tests/rules/test_manual_curve_review.py::test_manual_variant_replacement_uses_recipe_slot_identity -q`

Expected: FAIL because manual mutation functions do not exist.

- [ ] **Step 3: Add draft-only review models**

```python
class CurveCalibrationReview(FrozenModel):
    figure_artifact_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    calibration: ManualPlotCalibration
    calibration_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    actor: str = Field(min_length=1, max_length=200)
    recorded_at: datetime
    notes: NotesText


class CurveVariantReview(FrozenModel):
    variant_id: Identifier
    variant_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    source_artifact_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    calibration_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    input_origin: Literal["empty", "automatic_suggestion"]
    actor: str = Field(min_length=1, max_length=200)
    recorded_at: datetime
    notes: NotesText
```

Add `curve_calibrations: tuple[CurveCalibrationReview, ...] = ()` to `ImportedRuleDraft` and `_content_digest`. Do not add either draft-only model to `RulePackage` or archive files.

- [ ] **Step 4: Implement calibration save and manual variant replacement**

`set_manual_curve_calibration(...)` must bind one calibration to one immutable `RawFigure.artifact_sha256`, invalidate every review for that figure, and call `record_correction` once.

`replace_manual_curve_variant(...)` must:

1. Resolve `variant_id` against one recipe figure/slot without parsing source labels.
2. Require the current figure calibration.
3. Convert source X values to canonical rule units exactly once.
4. Validate points against reviewed bounds.
5. Infer segments with Task 1 helper.
6. Upsert the variant into one aggregate rule in recipe order.
7. Set `reviewed_artifact_sha256` to SHA-256 of figure artifact plus calibration hash.
8. Clear only that variant's old review.
9. Record one correction.

Keep `project_fault_time_voltage` as the exact final inventory/order validator. Add a small internal partial-rule builder in `review.py`; do not weaken `project_fault_time_voltage`.

- [ ] **Step 5: Write failing stale-calibration and unit-conversion tests**

```python
def test_calibration_change_invalidates_all_figure_reviews(reviewed_curve_draft) -> None:
    changed = set_manual_curve_calibration(
        reviewed_curve_draft,
        figure="5",
        calibration=_calibration().model_copy(update={"right": Decimal("321")}),
        actor="Reviewer",
        notes="Corrected synthetic plot corner.",
    )
    assert not tuple(
        review for review in changed.curve_variant_reviews
        if review.variant_id.startswith("synthetic.curve.5.")
    )


def test_source_duration_converts_once_to_rule_unit(synthetic_curve_draft) -> None:
    calibrated = set_manual_curve_calibration(
        synthetic_curve_draft,
        figure="5",
        calibration=_calibration(),
        actor="Reviewer",
        notes="Marked synthetic plot rectangle.",
    )
    changed = replace_manual_curve_variant(
        calibrated,
        variant_id="synthetic.curve.5.1",
        source_points=(
            CurvePoint(x=Decimal("1"), y=Decimal("100")),
            CurvePoint(x=Decimal("1000"), y=Decimal("20")),
        ),
        actor="Reviewer",
        notes="Entered synthetic curve points.",
        input_origin="empty",
    )
    variant = changed.curves[0].variants[0]
    assert variant.points[0].x == Decimal("0.001")
    assert variant.points[-1].x == Decimal("1")
```

- [ ] **Step 6: Implement manual review without conservatism proof**

`review_curve_variant(...)` must require actor/notes, exact current figure, exact calibration hash, exact variant hash, and one matching review item. It writes `CurveVariantReview`, resolves that item, and marks aggregate proposal reviewed only after every required current variant review exists. Remove rejection gating from this path.

- [ ] **Step 7: Run focused service tests**

Run: `uv run pytest tests/rules/test_manual_curve_review.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/insulation_coordination/rules/importer/extract.py src/insulation_coordination/rules/importer/review.py src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/projection.py tests/rules/test_manual_curve_review.py
git commit -m "feat: author curves from reviewed points"
```

### Task 3: Approval gates use exact manual evidence

**Files:**
- Modify: `src/insulation_coordination/rules/importer/approval.py:40-105,430-620,1250-1345`
- Modify: `tests/ui/test_semantic_review.py:200-470`
- Test: `tests/rules/test_manual_curve_review.py`

**Interfaces:**
- Consumes: Task 2 `CurveCalibrationReview`, extended `CurveVariantReview`.
- Produces: approval blockers based on current manual source/calibration/variant hashes only.

- [ ] **Step 1: Write failing approval tests**

```python
def test_manual_curve_review_clears_curve_blocker(reviewed_curve_draft) -> None:
    blockers = approval_blockers(reviewed_curve_draft)
    assert not tuple(item for item in blockers if item.kind == "curve")


def test_stale_manual_calibration_blocks_approval(reviewed_curve_draft) -> None:
    review = reviewed_curve_draft.curve_variant_reviews[0]
    stale = reviewed_curve_draft.model_copy(
        update={
            "curve_variant_reviews": (
                review.model_copy(update={"calibration_sha256": "f" * 64}),
            )
        }
    )
    assert any(item.code == "CURVE_VARIANT_REVIEW_REQUIRED" for item in approval_blockers(stale))
```

- [ ] **Step 2: Run tests and confirm old proof gate fails them**

Run: `uv run pytest tests/rules/test_manual_curve_review.py -q`

Expected: FAIL because approval still requires `CurveDigitizationResult.conservatism`.

- [ ] **Step 3: Replace proof checks with exact manual evidence checks**

For each required variant, require exactly one review where:

```python
review.variant_sha256 == canonical_model_sha256(variant)
review.source_artifact_sha256 == variant.reviewed_artifact_sha256
review.calibration_sha256 == current_calibration.calibration_sha256
```

Change blocker text to `lacks one exact current manual review`. Change `_review_resolution_exists` for curve items to check current reviewed variant evidence, not digitization/proof state.

- [ ] **Step 4: Update correction audit field lists**

Add `curve_calibrations` wherever draft-only fields participate in `_content_digest`, `raw_changed`, reconstructed `ImportedRuleDraft`, and correction audit tokens. Remove proof-only coupling that rejects calibration evidence changes unless `curve_digitizations` changes.

- [ ] **Step 5: Run approval and semantic-review tests**

Run: `uv run pytest tests/rules/test_manual_curve_review.py tests/ui/test_semantic_review.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/rules/importer/approval.py tests/rules/test_manual_curve_review.py tests/ui/test_semantic_review.py
git commit -m "fix: gate curves on manual review evidence"
```

### Task 4: Semantic variant labels and manual editor model

**Files:**
- Replace model portion: `src/insulation_coordination/ui/curve_review.py:1-260`
- Rewrite model tests: `tests/ui/test_curve_review.py:1-1136`

**Interfaces:**
- Consumes: Tasks 1-3 manual service functions and recipe selectors.
- Produces: `curve_variant_label(...)`, `CurveReviewModel.variant_entries`, `set_calibration(...)`, `replace_points(...)`, `review_variant(...)`.

- [ ] **Step 1: Write failing neutral-label tests**

```python
def test_variant_label_uses_selector_meaning_and_keeps_id_secondary() -> None:
    label = curve_variant_label(
        figure="5",
        variant_id="synthetic.curve.5.1",
        selector=FaultTimeVoltageSelector(
            subject="accessible_circuit",
            voltage_basis="dc",
            dvc_context="b",
            environment_context="dry",
        ),
    )
    assert label == "Figure 5 — Accessible circuit · DC · DVC B · Dry (synthetic.curve.5.1)"
```

Mappings are UI vocabulary for typed tokens, not copied source legend text.

- [ ] **Step 2: Run label test and confirm missing-function failure**

Run: `uv run pytest tests/ui/test_curve_review.py::test_variant_label_uses_selector_meaning_and_keeps_id_secondary -q`

Expected: FAIL because `curve_variant_label` does not exist.

- [ ] **Step 3: Replace `CurveReviewModel` correction surface**

Delete model methods `set_breakpoint`, old axis `set_calibration`, `set_segment`, `associate_trace`, `reject_variant`, `set_manual_points`, `recover_blocked`, and `manual_entry_enabled`.

Expose only:

```python
@property
def variant_entries(self) -> tuple[tuple[str, str], ...]: ...

def set_calibration(
    self,
    figure: str,
    calibration: ManualPlotCalibration,
    *,
    actor: str,
    notes: str,
) -> ImportedRuleDraft: ...

def replace_points(
    self,
    variant_id: str,
    source_points: tuple[CurvePoint, ...],
    *,
    actor: str,
    notes: str,
    input_origin: Literal["empty", "automatic_suggestion"] = "empty",
) -> ImportedRuleDraft: ...

def review_variant(
    self,
    variant_id: str,
    *,
    actor: str,
    notes: str,
) -> ImportedRuleDraft: ...
```

`variant_entries` comes from recipe slots plus current source figures, so empty drafts still show every required semantic variant.

- [ ] **Step 4: Add model tests for empty draft, replacement, and review**

```python
def test_empty_manual_draft_lists_every_recipe_slot(manual_draft) -> None:
    entries = CurveReviewModel(manual_draft).variant_entries
    assert tuple(identifier for _label, identifier in entries) == (
        "synthetic.curve.5.1",
        "synthetic.curve.5.2",
    )


def test_point_replacement_is_available_without_rejection(calibrated_manual_draft) -> None:
    model = CurveReviewModel(calibrated_manual_draft)
    model.replace_points(
        "synthetic.curve.5.1",
        (
            CurvePoint(x=Decimal("1"), y=Decimal("100")),
            CurvePoint(x=Decimal("1000"), y=Decimal("20")),
        ),
        actor="Reviewer",
        notes="Entered synthetic points.",
    )
    assert model.draft.curves[0].variants[0].points
```

- [ ] **Step 5: Run model tests**

Run: `uv run pytest tests/ui/test_curve_review.py -q -k 'label or model or replacement or review'`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/ui/curve_review.py tests/ui/test_curve_review.py
git commit -m "refactor: simplify curve review model"
```

### Task 5: Synchronized table, calibration, and draggable overlay

**Files:**
- Replace dialog portion: `src/insulation_coordination/ui/curve_review.py:261-789`
- Test: `tests/ui/test_curve_review.py`

**Interfaces:**
- Consumes: Task 4 model and Task 1 coordinate transforms.
- Produces: `_CurvePointHandle`, manual `CurveReviewDialog`, source-aligned scene coordinates.

- [ ] **Step 1: Write failing dialog tests for controls and source alignment**

```python
def test_dialog_starts_with_semantic_name_and_manual_controls(qtbot, local_manual_draft) -> None:
    draft, path = local_manual_draft
    dialog = CurveReviewDialog(
        draft,
        actor="Reviewer",
        pdf_paths={"SYNTHETIC": path},
    )
    qtbot.addWidget(dialog)

    assert "Accessible circuit" in dialog.current_variant_label
    assert dialog.point_table.columnCount() == 2
    assert dialog.calibration_button.text() == "Set plot and axes…"
    assert not hasattr(dialog, "_trace_button")
    assert not hasattr(dialog, "_segment_button")


def test_table_edit_redraws_overlay(qtbot, calibrated_dialog) -> None:
    calibrated_dialog.set_point_text(1, "10", "25")
    assert calibrated_dialog.overlay_path.elementCount() == calibrated_dialog.point_table.rowCount()
```

- [ ] **Step 2: Run dialog tests and confirm old-control failure**

Run: `uv run pytest tests/ui/test_curve_review.py -q -k 'dialog or overlay or table'`

Expected: FAIL because old dialog has correction buttons and no point table.

- [ ] **Step 3: Build persistent manual layout**

Use existing `QGraphicsView`. Add `QTableWidget` with X/Y columns, Add point, Remove point, `Set plot and axes…`, `Save points`, `Accept variant`, and Close. Keep notes required for calibration, save, and acceptance.

Calibration interaction records two scene clicks in order: top-left then bottom-right. Prompt for four axis bounds using line edits parsed directly into `Decimal`. Reject malformed input without mutating model.

- [ ] **Step 4: Add movable handle with constrained callback**

```python
class _CurvePointHandle(QGraphicsEllipseItem):
    def __init__(self, index: int, moved: Callable[[int, QPointF], None]) -> None:
        super().__init__(-5, -5, 10, 10)
        self._index = index
        self._moved = moved
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)

    def itemChange(self, change, value):  # type: ignore[no-untyped-def]
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self._moved(self._index, value)
        return super().itemChange(change, value)
```

Clamp handles to reviewed plot rectangle and between neighboring X handles. Convert movement through `pixel_to_source_point`, write Decimal text into table, then redraw. Table edits use `source_point_to_pixel` and move handles without recursive callbacks.

- [ ] **Step 5: Add drag/table synchronization and invalid-input tests**

```python
def test_handle_move_updates_exact_table_values(calibrated_dialog) -> None:
    calibrated_dialog.move_handle(1, Decimal("120"), Decimal("110"))
    assert calibrated_dialog.point_text(1) == (
        "10",
        "10",
    )


def test_invalid_table_edit_does_not_mutate_draft(calibrated_dialog) -> None:
    before = calibrated_dialog.draft
    calibrated_dialog.set_point_text(0, "not-a-number", "10")
    calibrated_dialog.save_points()
    assert calibrated_dialog.draft == before
    assert "valid decimal" in calibrated_dialog.status_text.lower()
```

- [ ] **Step 6: Fix overlay coordinate ownership**

Draw source crop, plot rectangle, handles, and overlay in one scene coordinate system. Do not scale XObject pixel coordinates over the full crop and do not use `RawFigure.transform` for manually reviewed points. The reviewer's scene-space rectangle is the coordinate authority, eliminating the current ignored-transform bug.

- [ ] **Step 7: Run all curve UI tests**

Run: `uv run pytest tests/ui/test_curve_review.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/insulation_coordination/ui/curve_review.py tests/ui/test_curve_review.py
git commit -m "feat: add manual curve point editor"
```

### Task 6: Cut importer over to source-only figures and delete automatic reconstruction

**Files:**
- Modify: `src/insulation_coordination/rules/importer/curves.py`
- Modify: `src/insulation_coordination/rules/importer/extract.py:1690-2048`
- Modify: `src/insulation_coordination/rules/importer/review.py:1708-2859`
- Modify: `src/insulation_coordination/rules/importer/approval.py`
- Modify: `tests/rules/test_curve_source_extraction.py`
- Modify: `tests/rules/importer/iec62477_2022/test_figure_curve_proposals.py`
- Delete: `tests/rules/test_curve_ocr.py`
- Delete: `tests/rules/test_log_curve_digitization.py`
- Delete: `tests/rules/test_conservative_curves.py`

**Interfaces:**
- Consumes: Tasks 1-5 manual path.
- Produces: source-only extraction with no Tesseract, trace ordering, or conservative-proof dependency.

- [ ] **Step 1: Write failing source-only extraction test**

```python
def test_curve_import_creates_source_figures_and_manual_review_items(
    synthetic_curve_pdf,
) -> None:
    figures, curves, proposals, review_items = _extract_curve_artifacts(
        synthetic_curve_pdf.path,
        synthetic_curve_pdf.identity,
        synthetic_curve_pdf.recipe,
    )

    assert len(figures) == 1
    assert curves == ()
    assert proposals == ()
    assert tuple(item.code for item in review_items) == (
        "CURVE_VARIANT_REVIEW_REQUIRED",
        "CURVE_VARIANT_REVIEW_REQUIRED",
    )
```

- [ ] **Step 2: Run source tests and confirm old return-shape failure**

Run: `uv run pytest tests/rules/test_curve_source_extraction.py tests/rules/importer/iec62477_2022/test_figure_curve_proposals.py -q`

Expected: FAIL because extraction still requires OCR/digitization and returns digitization results.

- [ ] **Step 3: Simplify `RawFigure` and `extract_raw_figure`**

Keep source, source mode, source bbox, pixel size, placement transform, and artifact SHA-256. Remove OCR tokens and traced strokes. Preserve vector/image source detection, lossless-image checks, clipping checks, and deterministic source hashing.

Change `extract_raw_figure` signature to:

```python
def extract_raw_figure(
    reader_page: PageObject,
    plumber_page: pdfplumber.page.Page,
    spec: CurveAuditSpec,
    identity: StandardIdentity,
) -> RawFigure: ...
```

- [ ] **Step 4: Simplify extraction orchestration**

Remove `ocr_engine` from `extract_draft`, `_extract_one`, and `_extract_curve_artifacts`. Curve import returns source figures and one manual review item per declared slot, with no curve/proposal until manual point entry creates one.

- [ ] **Step 5: Delete obsolete implementation**

Delete from `curves.py`: OCR adapter/types, TSV parser, raster/vector trace recovery, automatic axis fitting, simplification, conservatism proof, digitization result, and rebuild functions.

Delete from `extract.py`, `review.py`, and `approval.py`: `CurveDigitizationResult`, `CurveTraceAssociation`, `ManualCurveTrace`, `CurveVariantRejection`, related draft fields/digests/model rebuilds, trace association, rejection, breakpoint/segment correction, automatic recovery, and proof validation.

Run `rg` to prove no caller remains:

```bash
rg -n "TesseractOcrEngine|CurveDigitizationResult|CurveTraceAssociation|ManualCurveTrace|CurveVariantRejection|prove_variant_conservative|associate_curve_trace|correct_curve_calibration|replace_curve_breakpoint|replace_curve_segment" src tests
```

Expected: no output.

- [ ] **Step 6: Rewrite retained extraction tests**

Keep tests for verified figure location, deterministic artifact hashing, vector preference, lossless image fallback, placement transform retention, clipping refusal, lossy-image refusal, and ambiguous/missing source refusal. Remove expectations about OCR tokens and traced colored lines.

- [ ] **Step 7: Run importer and review suites**

Run: `uv run pytest tests/rules/test_curve_source_extraction.py tests/rules/test_manual_curve_review.py tests/rules/importer/iec62477_2022/test_figure_curve_proposals.py tests/ui/test_curve_review.py tests/ui/test_semantic_review.py -q`

Expected: PASS.

- [ ] **Step 8: Commit deletion**

```bash
git add -A src/insulation_coordination/rules/importer tests/rules tests/ui
git commit -m "refactor: remove automatic curve digitization"
```

### Task 7: Compatibility, private workflow, docs, and full verification

**Files:**
- Modify: `tests/private/test_iec62477_curves.py`
- Modify: `tests/ui/test_rules_manager_review.py`
- Modify: `tests/rules/test_archive.py`
- Modify: `tests/rules/test_curve_evaluation.py`
- Modify: `AGENTS.md`
- Modify only if current text mentions automatic digitization: `README.md`

**Interfaces:**
- Consumes: complete manual workflow.
- Produces: end-to-end confidence, accurate maintainer instructions, no licensed fixtures.

- [ ] **Step 1: Add approved-package compatibility test**

Extend `tests/rules/test_archive.py::test_approved_package_loads_without_source_pdfs` using its existing `synthetic_package` fixture. Assert the loaded package preserves `synthetic_package.curves`, then evaluate the loaded first variant at its first point and assert the same value. Do not create a migration or modify archive schema.

- [ ] **Step 2: Rewrite private curve test around structure**

Private test must assert source figures are found, manual review items match recipe slot inventory, a maintainer-entered local review can build every variant, approval succeeds, export/re-import preserves final curve hashes, and evaluation works. Values remain computed/read locally and are never printed or snapshot into test source.

- [ ] **Step 3: Run focused package and Rules Manager tests**

Run: `uv run pytest tests/rules/test_archive.py tests/rules/test_curve_evaluation.py tests/ui/test_rules_manager_review.py tests/ui/test_curve_review.py tests/rules/test_manual_curve_review.py -q`

Expected: PASS.

- [ ] **Step 4: Run required static checks**

Run: `uv run ruff check .`

Expected: PASS.

Run: `uv run mypy`

Expected: PASS.

- [ ] **Step 5: Run full public suite with coverage**

Run: `uv run pytest -n auto --cov=insulation_coordination --cov-branch --cov-report=term-missing --cov-fail-under=80`

Expected: PASS with at least 80% branch-aware coverage.

- [ ] **Step 6: Run licensed suite when standards are available**

Run: `uv run pytest tests/private -q --timeout=900`

Expected: PASS. Do not edit source while this run is active. If licensed files are absent, record that the private suite was skipped; do not claim it passed.

- [ ] **Step 7: Update maintainer instructions from measured behavior**

Remove Tesseract installation/PATH guidance from `AGENTS.md`. Replace automatic-digitization timing claims with measured source-only/manual-review expectations from Step 6. Do not place source values or labels in docs.

- [ ] **Step 8: Verify no licensed or obsolete content entered Git**

Run:

```bash
git status --short
git diff --check
rg -n "Tesseract|OCR_UNAVAILABLE|CURVE_CONSERVATISM_UNPROVEN|CURVE_TRACE_AMBIGUOUS" src tests AGENTS.md README.md
```

Expected: only intended files changed; `git diff --check` clean; obsolete-token search empty. Existing untracked `audit/`, `projects/`, and `tmp/` remain untouched and unstaged.

- [ ] **Step 9: Commit final integration**

```bash
git add tests/private/test_iec62477_curves.py tests/ui/test_rules_manager_review.py tests/rules/test_archive.py tests/rules/test_curve_evaluation.py AGENTS.md README.md
git commit -m "test: verify manual curve review workflow"
```

- [ ] **Step 10: Review final diff**

Run: `git diff origin/main...HEAD --stat`

Expected: curve workflow simplified, obsolete digitizer code removed, no unrelated files or private artifacts included.
