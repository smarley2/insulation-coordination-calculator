# IEC 62477-1:2022 DVC and Curve Extraction — Slice C Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Slice C as three independently testable PRs: schema-v4 semantic foundation, structured DVC/Table 7 extraction, then automatic reviewed Figure 5–7 digitization and private end-to-end verification.

**Architecture:** Final `RulePackage` objects remain executable by construction. Importer-only `SemanticProposal` records carry proposed/reviewed state and disappear at approval. Schema v4 adds typed document/page provenance, real boolean matching, and first-class piecewise curves whose semantic points contain engineering quantities only. Figure extraction is vector-first, uses the lossless embedded XObject when paths are absent, calibrates logarithmic axes through an injected OCR engine, proves a conservative envelope, and blocks every uncertain result.

**Tech Stack:** Python 3.12, pydantic v2 frozen models, `Decimal`, pypdf, pdfplumber, explicit Pillow `>=12,<13`, PySide6/QImage/QGraphicsView, local optional Tesseract CLI behind `OcrEngine`, pytest, pytest-qt, Hypothesis, ruff, strict mypy, uv.

## Global Constraints

- Public code/tests contain no licensed IEC values, wording, labels, footnotes, source curve coordinates, screenshots, XObjects, reconstructed curves, PDFs, or private `.icrules`.
- Public content may contain semantic IDs, figure/table/clause numbers, page/bbox/shape locators, neutral labels, generic algorithms, and deliberately unrelated synthetic fixtures.
- Actual IEC values, curve points, OCR text, source images, corrections, and golden artifacts stay in ignored private workspaces/tests and approved private packages.
- Never hard-code a missing extracted value or fallback. Ambiguity creates a blocking review item.
- Table 2 references `iec62477_2022.dvc.fault_time_voltage`; it never duplicates Figure 5–7 curve values.
- Table 2 keeps Table 7 references semantic; it never duplicates Table 7 data.
- Table 7 preserves separate source quantities, AC/DC routes, and impulse/TOV semantic families.
- Final rules contain no `executable` flag. `SemanticProposal` owns draft state; approval emits an executable-by-construction `RulePackage` without proposal metadata.
- Approved `CurvePoint` contains engineering x/y only. Source geometry lives in `RawCurvePoint` and links through a reviewed artifact SHA-256.
- Curve selection uses exact typed keys. Zero matches is explicit; multiple matches is an error; first-match-wins is forbidden.
- Curve evaluation never extrapolates. A plateau extends only through an explicit reviewed constant segment/domain.
- Approved reconstructed maximum-voltage limits never exceed the conservative lower envelope of source geometry plus calibration uncertainty.
- C1, C2, and C3 each use `Refs #34`; none closes #34. Slice C completes only after C3.
- Issues #35, #36, and #37 runtime UI remain out of scope.
- Every production behavior follows red-green-refactor. Each test names the production mutation it catches and exercises real code.
- Before each PR: run ruff, strict mypy, focused/full branch-aware pytest at `--cov-fail-under=80`; C2/C3 also run relevant private tests.
- Private commands read licensed PDFs from ignored `standards/` by default; maintainers may override with `ICC_PRIVATE_STANDARDS_DIR`.

## File Map

- `domain/rules.py`: final schema-v4 source, decision, and curve semantics only.
- `rules/importer/extract.py`: generic raw artifacts, proposal records, and draft digests.
- `rules/importer/curves.py`: OCR boundary, source geometry, calibration, tracing, and conservative proof.
- `rules/importer/projection.py`: generic raw-to-semantic projection helpers.
- `rules/importer/review.py` and `approval.py`: corrections, exact-hash review, and final-package gate.
- `rules/importer/recipes/iec62477_1_2022/{tables,clauses,curves,projection}.py`: IEC structural recipes and semantic routing; no licensed literals.
- `rules/{archive,validation,audit}.py`: final curve persistence and integrity checks.
- `ui/{semantic_review,curve_review,rules_manager}.py`: local-only review surfaces and source overlay.
- `tests/rules` and `tests/ui`: unrelated synthetic fixtures; `tests/private`: runtime licensed-PDF proofs without committed expected values.

---

## PR C1 — Semantic foundation

PR title: `IEC 62477 Slice C1: semantic foundation`

PR body trailer: `Refs #34`

### Task 1: Schema v4 typed source-document provenance

**Files:**
- Modify: `src/insulation_coordination/domain/rules.py`
- Modify: `src/insulation_coordination/rules/importer/extract.py`
- Modify: `src/insulation_coordination/rules/importer/projection.py`
- Modify: `src/insulation_coordination/rules/importer/review.py`
- Modify: `src/insulation_coordination/rules/importer/approval.py`
- Modify: `src/insulation_coordination/rules/validation.py`
- Test: `tests/fixtures/synthetic_rules.py`
- Test: `tests/rules/test_source_provenance.py`
- Test: `tests/report/test_latex.py`
- Test: `tests/rules/test_archive.py`
- Test: `tests/rules/test_decision_evaluation.py`
- Test: `tests/rules/test_decision_rules.py`
- Test: `tests/rules/test_evaluator.py`
- Test: `tests/rules/test_importer.py`
- Test: `tests/rules/test_power_expression.py`
- Test: `tests/rules/test_procedure_and_guidance_rules.py`
- Test: `tests/ui/test_equation_review.py`

**Interfaces:**
- Consumes: existing `StandardIdentity.recipe_id`, `StandardIdentity.standard`, `StandardIdentity.edition`, `StandardIdentity.sha256`; existing `Manifest.source_documents`.
- Produces: `SourceDocument.id: Identifier`; `SourceGeometryReference`; `SourceReference.document_id`; `SourceReference.page`; both importer `_source` helpers populate typed `document_id`/`page` from their existing `identity` and keyword-only `page_number` inputs; validation code `SOURCE_DOCUMENT_LINKS_VALID`.

- [ ] **Step 1: Write failing provenance tests**

Write these tests with synthetic identities only:

```python
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

def test_package_rejects_unknown_source_document_link() -> None:
    package = synthetic_package()
    bad = package.model_copy(
        update={
            "tables": (
                package.tables[0].model_copy(
                    update={"source": package.tables[0].source.model_copy(
                        update={"document_id": "missing-source"}
                    )}
                ),
                *package.tables[1:],
            )
        }
    )
    report = validate_rule_package(bad)
    assert "SOURCE_DOCUMENT_LINKS_VALID" in {
        item.code for item in report.results if not item.passed
    }
```

Also test: page zero rejected; SHA/bbox validation; reference standard/edition mismatch rejected; schema 3 archive rejected with rebuild message; imported source page is not encoded in `note`.

- [ ] **Step 2: Run tests and confirm red**

Run:

```bash
uv run pytest tests/rules/test_source_provenance.py tests/rules/test_archive.py -q
```

Expected: FAIL because `SourceDocument.id`, `SourceReference.document_id/page`, geometry, and link validation do not exist.

- [ ] **Step 3: Implement schema/provenance minimally**

In `domain/rules.py`:

```python
RULE_SCHEMA_VERSION = 4
IEC_IMPORTER_VERSION = "iec-pdf-4"

class SourceGeometryReference(FrozenModel):
    artifact_sha256: str
    bbox: tuple[DecimalValue, DecimalValue, DecimalValue, DecimalValue] | None = None

class SourceReference(FrozenModel):
    document_id: Identifier
    standard: Identifier
    edition: Identifier
    page: int | None = Field(default=None, ge=1, strict=True)
    clause: ReferenceText | None = None
    table: ReferenceText | None = None
    figure: ReferenceText | None = None
    row: ReferenceText | None = None
    column: ReferenceText | None = None
    geometry: SourceGeometryReference | None = None
    note: ReferenceText | None = None

class SourceDocument(FrozenModel):
    id: Identifier
    standard: Identifier
    edition: Identifier
    sha256: str
```

Validate SHA-256 and ordered bboxes. Imported IEC documents use `StandardIdentity.recipe_id` as `SourceDocument.id`. Update every `_source` helper to pass `document_id=identity.recipe_id` and `page=page_number`; remove `note=f"PDF page {page_number}"`. Update synthetic fixtures with `id="synthetic-source"`. Package validation resolves every source found by `rules.audit._source_references` against exactly one manifest document and checks standard/edition equality.

- [ ] **Step 4: Run focused tests and confirm green**

```bash
uv run pytest tests/rules/test_source_provenance.py tests/rules/test_archive.py tests/rules/test_importer.py -q
```

Expected: PASS.

- [ ] **Step 5: Run neighboring tests**

```bash
uv run pytest tests/rules tests/ui/test_equation_review.py tests/report/test_latex.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/domain/rules.py src/insulation_coordination/rules/importer src/insulation_coordination/rules/validation.py tests/fixtures/synthetic_rules.py tests/rules tests/ui/test_equation_review.py tests/report/test_latex.py
git commit -m "feat(rules): add typed source provenance"
```

### Task 2: Boolean decision matching and exhaustiveness

**Files:**
- Modify: `src/insulation_coordination/domain/rules.py`
- Modify: `src/insulation_coordination/rules/evaluator.py`
- Test: `tests/rules/test_decision_rules.py`
- Test: `tests/rules/test_decision_evaluation.py`

**Interfaces:**
- Consumes: `DecisionInput(kind="boolean")`, `DecisionRule`, `evaluate_decision`.
- Produces: `Matcher.boolean: bool | None`; boolean `equals`; `_decision_domains`; exhaustive Cartesian coverage across categorical and boolean inputs; deterministic true/false evaluation.

- [ ] **Step 1: Write failing boolean tests**

Use updated schema-v4 synthetic `SOURCE`. Add this helper and assertions:

```python
def _boolean_rule(*, include_false: bool = True, mixed: bool = False) -> DecisionRule:
    inputs = (DecisionInput(name="enabled", kind="boolean"),)
    combinations: tuple[tuple[bool, str | None, str], ...] = (
        ((True, None, "path-a"),)
        + (((False, None, "path-b"),) if include_false else ())
    )
    if mixed:
        inputs += (DecisionInput(name="mode", kind="categorical", allowed_values=("x", "y")),)
        combinations = (
            (True, "x", "path-a"),
            (False, "x", "path-b"),
            (True, "y", "path-b"),
            (False, "y", "path-a"),
        )
    rows = tuple(
        DecisionRow(
            matchers=(Matcher(input="enabled", op="equals", boolean=enabled),)
            + ((Matcher(input="mode", op="equals", values=(mode,)),) if mode else ()),
            values=(DecisionValue(name="route", categorical=route),),
            source=SOURCE,
        )
        for enabled, mode, route in combinations
    )
    return DecisionRule(
        id="synthetic-boolean",
        inputs=inputs,
        outputs=(DecisionOutput(name="route", kind="categorical", allowed_values=("path-a", "path-b")),),
        rows=rows,
        exhaustive=True,
        source=SOURCE,
    )

rule = _boolean_rule()
assert evaluate_decision(rule, {"enabled": True}).values[0].categorical == "path-a"
assert evaluate_decision(rule, {"enabled": False}).values[0].categorical == "path-b"
assert evaluate_decision(rule, {}).status == "input_required"
with pytest.raises(ValueError, match="does not cover"):
    _boolean_rule(include_false=False)
mixed = _boolean_rule(mixed=True)
assert {
    evaluate_decision(mixed, {"enabled": enabled, "mode": mode}).values[0].categorical
    for enabled in (False, True)
    for mode in ("x", "y")
} == {"path-a", "path-b"}
with pytest.raises(ValueError, match="boolean"):
    DecisionRule(
        id="synthetic-string-boolean",
        inputs=(DecisionInput(name="enabled", kind="boolean"),),
        outputs=(DecisionOutput(name="route", kind="categorical", allowed_values=("path-a",)),),
        rows=(DecisionRow(
            matchers=(Matcher(input="enabled", op="equals", values=("true",)),),
            values=(DecisionValue(name="route", categorical="path-a"),),
            source=SOURCE,
        ),),
        exhaustive=False,
        source=SOURCE,
    )
```

Split these assertions into named tests. The incomplete exhaustive rule must fail construction;
the four-row mixed rule must construct and evaluate all combinations. Add evaluator checks that
integers `0`/`1` do not satisfy boolean matchers.

- [ ] **Step 2: Run tests and confirm red**

```bash
uv run pytest tests/rules/test_decision_rules.py tests/rules/test_decision_evaluation.py -q
```

Expected: FAIL because boolean equality and boolean exhaustive domains are unsupported.

- [ ] **Step 3: Implement boolean support minimally**

In `Matcher` add `boolean: bool | None = None`. Validation rules:

```python
if self.op == "equals" and self.boolean is not None:
    if self.values or self.minimum is not None or self.maximum is not None:
        raise ValueError("A boolean equals matcher uses only boolean")
elif self.boolean is not None:
    raise ValueError("Only equals may declare boolean")
```

In `DecisionRule._rows_agree_with_declarations`, accept `equals` on categorical inputs via one string value or on boolean inputs via `boolean`. Reject `in` for boolean. Replace the boolean-exhaustiveness refusal with domains:

```python
domains = tuple(
    item.allowed_values if item.kind == "categorical" else (False, True)
    for item in inputs.values()
    if item.kind in ("categorical", "boolean")
)
```

Update `_row_admits` and evaluator `_matches` to compare actual booleans without Python's `bool == 1` coercion.

- [ ] **Step 4: Run focused tests and confirm green**

```bash
uv run pytest tests/rules/test_decision_rules.py tests/rules/test_decision_evaluation.py -q
```

Expected: PASS.

- [ ] **Step 5: Run neighboring tests**

```bash
uv run pytest tests/rules/test_evaluator.py tests/rules/test_procedure_and_guidance_rules.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/domain/rules.py src/insulation_coordination/rules/evaluator.py tests/rules/test_decision_rules.py tests/rules/test_decision_evaluation.py
git commit -m "feat(rules): support boolean decision matching"
```

### Task 3: Piecewise curve model, exact selector, and evaluator

**Files:**
- Modify: `src/insulation_coordination/domain/rules.py`
- Modify: `src/insulation_coordination/rules/evaluator.py`
- Modify: `src/insulation_coordination/rules/validation.py`
- Modify: `src/insulation_coordination/rules/importer/iec62477_2022/inventory.py`
- Test: `tests/rules/importer/iec62477_2022/test_inventory.py`
- Test: `tests/rules/test_piecewise_curves.py`
- Test: `tests/rules/test_curve_evaluation.py`

**Interfaces:**
- Consumes: `DecimalValue`, `SourceReference`, `EvaluationError`.
- Produces: shared `RuleKind`; `CurveAxis`; `CurvePoint`; `CurveSegment`; `FaultTimeVoltageSelector`; `FaultTimeVoltageVariant`; `PiecewiseCurveRule`; `CurveSelectionResult`; `CurveEvaluationResult`; `select_curve_variant`; `evaluate_piecewise_curve`.

- [ ] **Step 1: Write failing curve model/evaluator tests**

Use a local `_synthetic_curve` helper with points `(3, 777)`, `(27, 271)`, `(243, 89)`, two
continuous `log_log` segments, and selector
`("accessible_circuit", "dc", "synthetic-dvc", None)`.
Its source uses only synthetic provenance. Add these exact assertions:

```python
assert set(CurvePoint.model_fields) == {"x", "y"}
assert select_curve_variant(rule, exact_selector).status == "matched"
assert select_curve_variant(rule, exact_selector.model_copy(update={"dvc_context": None})).status == "no_match"
with pytest.raises(ValueError, match="selector"):
    PiecewiseCurveRule(id=rule.id, variants=(rule.variants[0], rule.variants[0]), source=SOURCE)
with pytest.raises(EvaluationError, match="multiple"):
    select_curve_variant(unvalidated_duplicate_rule, exact_selector)
assert evaluate_piecewise_curve(rule, exact_selector, Decimal("3")).status == "matched"
assert evaluate_piecewise_curve(rule, exact_selector, Decimal("243")).status == "matched"
assert evaluate_piecewise_curve(rule, exact_selector, Decimal("2")).status == "out_of_domain"
assert evaluate_piecewise_curve(rule, exact_selector, Decimal("244")).status == "out_of_domain"
assert evaluate_piecewise_curve(rule, exact_selector, Decimal("27")).value == Decimal("271")
```

Add a separate explicit `segment_type="plateau", interpolation="constant"` segment ending at
x=`300`; x=`300` matches its plateau and
x=`301` returns `out_of_domain`. Compare the log-log midpoint with a 34-digit local-`Decimal`
calculation. Use `model_construct` only for the runtime duplicate-defense test.

- [ ] **Step 2: Run tests and confirm red**

```bash
uv run pytest tests/rules/test_piecewise_curves.py tests/rules/test_curve_evaluation.py -q
```

Expected: FAIL because curve types/evaluator do not exist.

- [ ] **Step 3: Implement minimal curve semantics**

Add these exact model shapes; validators enforce ordered finite points, positive log-axis bounds,
adjacent complete segments, in-range points, unique variant IDs/selectors, and valid SHA-256:

```python
CurveAxisScale = TypingLiteral["linear", "log10"]
CurveSegmentType = TypingLiteral["continuous", "plateau", "step"]
CurveInterpolation = TypingLiteral[
    "linear", "log_x", "log_y", "log_log", "constant", "step_before", "step_after"
]

class CurveAxis(FrozenModel):
    quantity_kind: Identifier
    unit: Identifier
    scale: CurveAxisScale
    minimum: DecimalValue
    maximum: DecimalValue

class CurvePoint(FrozenModel):
    x: DecimalValue
    y: DecimalValue

class CurveSegment(FrozenModel):
    start: int
    end: int
    segment_type: CurveSegmentType
    interpolation: CurveInterpolation

class FaultTimeVoltageSelector(FrozenModel):
    subject: TypingLiteral["accessible_circuit", "conductive_accessible_part"]
    voltage_basis: TypingLiteral["ac_rms", "ac_peak", "dc"]
    dvc_context: Identifier | None
    environment_context: Identifier | None

class FaultTimeVoltageVariant(FrozenModel):
    id: Identifier
    selector: FaultTimeVoltageSelector
    x_axis: CurveAxis
    y_axis: CurveAxis
    points: tuple[CurvePoint, ...]
    segments: tuple[CurveSegment, ...]
    applicability: ApplicabilityText
    source: SourceReference
    reviewed_artifact_sha256: str

class PiecewiseCurveRule(FrozenModel):
    id: Identifier
    variants: tuple[FaultTimeVoltageVariant, ...]
    source: SourceReference
```

Validate `continuous` with linear/log interpolation, `plateau` with equal endpoint voltage and
`constant`, and `step` with `step_before`/`step_after`. `FaultTimeVoltageSelector` requires all fields; callers pass `None` explicitly for
not-applicable dimensions. Define shared `RuleKind` in `domain/rules.py` as
`Literal["table", "formula", "mapping", "decision", "procedure", "guidance", "curve"]`.
Make IEC inventory import it and change `iec62477_2022.dvc.fault_time_voltage` from `decision` to
`curve`. `FaultTimeVoltageVariant` stores `reviewed_artifact_sha256`, not raw points.

Use result models:

```python
class CurveSelectionResult(FrozenModel):
    status: TypingLiteral["matched", "no_match"]
    variant: FaultTimeVoltageVariant | None = None

class CurveEvaluationResult(FrozenModel):
    status: TypingLiteral["matched", "no_match", "out_of_domain"]
    value: DecimalValue | None = None
    unit: Identifier | None = None
    variant_id: Identifier | None = None
    source: SourceReference | None = None
```

`select_curve_variant` compares selector objects for exact equality, returns `no_match` for zero, and raises `EvaluationError` for multiple. `evaluate_piecewise_curve` refuses x outside `[first.x, last.x]`; no segment continuation. Implement declared `linear`, `log_x`, `log_y`, `log_log`, `constant`, `step_before`, and `step_after` with `Decimal` local contexts only.

- [ ] **Step 4: Run focused tests and confirm green**

```bash
uv run pytest tests/rules/test_piecewise_curves.py tests/rules/test_curve_evaluation.py -q
```

Expected: PASS.

- [ ] **Step 5: Run neighboring tests**

```bash
uv run pytest tests/rules/test_evaluator.py tests/rules/test_decision_evaluation.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/domain/rules.py src/insulation_coordination/rules/evaluator.py src/insulation_coordination/rules/validation.py src/insulation_coordination/rules/importer/iec62477_2022/inventory.py tests/rules/importer/iec62477_2022/test_inventory.py tests/rules/test_piecewise_curves.py tests/rules/test_curve_evaluation.py
git commit -m "feat(rules): add piecewise curve semantics"
```

### Task 4: Draft semantic-proposal lifecycle

**Files:**
- Modify: `src/insulation_coordination/rules/importer/extract.py`
- Modify: `src/insulation_coordination/rules/importer/review.py`
- Modify: `src/insulation_coordination/rules/importer/approval.py`
- Modify: `src/insulation_coordination/rules/importer/iec62477_2022/inventory.py`
- Test: `tests/rules/test_semantic_proposals.py`
- Test: `tests/rules/test_importer.py`
- Test: `tests/ui/test_rules_manager_review.py`

**Interfaces:**
- Consumes: `ImportedRuleDraft`, canonical JSON/hash helpers, `record_correction`, `approve_draft`.
- Produces: `ReviewArtifactKind`; `ProposalState`; `SemanticProposal`; `ImportedRuleDraft.semantic_proposals`; `canonical_model_sha256`; `proposal_for`; `mark_proposal_reviewed`; `approval_blockers`; approval requires exact reviewed hashes and emits no proposal metadata.

- [ ] **Step 1: Write failing lifecycle tests**

```python
proposal = proposal_for(draft, draft.tables[0].id)
assert proposal.state == "proposed"
reviewed = mark_proposal_reviewed(draft, proposal.semantic_id, actor="tester", notes="synthetic")
assert proposal_for(reviewed, proposal.semantic_id).state == "reviewed"
corrected = record_correction(reviewed, synthetic_rule_correction(proposal.semantic_id))
assert proposal_for(corrected, proposal.semantic_id).state == "proposed"
with pytest.raises(ApprovalError, match="stale"):
    approve_draft(stale_review_hash(corrected), synthetic_approval())
with pytest.raises(ApprovalError, match="proposed"):
    approve_draft(draft_with_unreviewed_procedure(), synthetic_approval())
package = approve_draft(review_all_synthetic_proposals(draft), synthetic_approval())
assert "semantic_proposals" not in package.model_fields
```

Test helpers construct fully synthetic corrections/approval records. Parameterize the first four
assertions across every `RuleKind`: table, formula, mapping, decision, procedure, guidance,
curve. Expand inventory `RuleKind` with `mapping` and `curve`.

- [ ] **Step 2: Run tests and confirm red**

```bash
uv run pytest tests/rules/test_semantic_proposals.py tests/rules/test_importer.py tests/ui/test_rules_manager_review.py -q
```

Expected: FAIL because proposal records and hash gates do not exist.

- [ ] **Step 3: Implement proposal lifecycle minimally**

In `extract.py`:

```python
ProposalState = Literal["proposed", "reviewed"]

class SemanticProposal(FrozenModel):
    semantic_id: Identifier
    rule_kind: RuleKind
    state: ProposalState
    rule_sha256: str
    source_artifact_sha256: str
    review_item_sha256s: tuple[str, ...] = ()

class ImportedRuleDraft(DraftRulePackage):
    semantic_proposals: tuple[SemanticProposal, ...] = ()
    # existing review/raw fields remain
```

Hash the canonical typed rule payload. For one raw artifact, use that artifact digest directly; for
multiple artifacts, hash canonical ordered `(artifact_id, artifact_sha256)` pairs.
`mark_proposal_reviewed` verifies current rule hash, aggregate artifact hash, and every required
member review-item hash. `record_correction` resets only changed proposal IDs. `approve_draft`
checks required unique reviewed proposals, then constructs `RulePackage` with all final
collections (`tables`, `formulas`, `mappings`, `decisions`, `procedures`, `guidance`, `curves`)
and no draft fields.

Implement `approval_blockers(draft: ImportedRuleDraft) -> tuple[ImportReviewItem, ...]` as the
single gate used by both UI and `approve_draft`; `approve_draft` raises when this tuple is nonempty.

Define `canonical_model_sha256(value: FrozenModel) -> str` once in `extract.py` from
`rules.archive._canonical_json(value.model_dump(mode="json", warnings=False))`; all proposal,
review, determinism, and correction tests call this helper. Import shared `RuleKind` from Task 3.
Define
`ReviewArtifactKind = Literal["table", "formula", "mapping", "raw_cell", "semantic", "clause",
"curve"]`; change `ImportReviewItem.code` to `Identifier` and its `kind` to
`ReviewArtifactKind`, preserving exact stable codes in each producer.

- [ ] **Step 4: Run focused tests and confirm green**

```bash
uv run pytest tests/rules/test_semantic_proposals.py tests/rules/test_importer.py tests/ui/test_rules_manager_review.py -q
```

Expected: PASS.

- [ ] **Step 5: Run neighboring tests**

```bash
uv run pytest tests/rules/test_archive.py tests/rules/test_procedure_and_guidance_rules.py tests/ui/test_equation_review.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/rules/importer tests/rules/test_semantic_proposals.py tests/rules/test_importer.py tests/ui/test_rules_manager_review.py
git commit -m "feat(importer): separate semantic proposal lifecycle"
```

### Task 5: Curve archive, validation, audit, report, and synthetic fixtures

**Files:**
- Modify: `src/insulation_coordination/domain/rules.py`
- Modify: `src/insulation_coordination/rules/archive.py`
- Modify: `src/insulation_coordination/rules/validation.py`
- Modify: `src/insulation_coordination/rules/audit.py`
- Modify: `src/insulation_coordination/report/model.py`
- Modify: `src/insulation_coordination/ui/rules_manager.py`
- Test: `tests/fixtures/synthetic_rules.py`
- Test: `tests/rules/test_archive.py`
- Test: `tests/rules/test_audit.py`
- Test: `tests/report/test_model.py`
- Test: `tests/ui/test_rules_manager.py`

**Interfaces:**
- Consumes: `PiecewiseCurveRule`, `RulePackage`, existing deterministic archive/audit patterns.
- Produces: `RulePackage.curves`; `curves.json`; `AuditInventory.curves/curve_count`; curve source references; Rule Manager `Curves` audit section and `audit_curve_count`; `RulesProvenance.curve_count`.

- [ ] **Step 1: Write failing round-trip/audit tests**

Add one synthetic curve to `synthetic_package`. Assert:

```python
path = tmp_path / "synthetic.icrules"
write_rule_package(path, synthetic_rule_package())
loaded = load_rule_package(path)
assert loaded.curves == synthetic_rule_package().curves
with ZipFile(path) as archive:
    checksums = json.loads(archive.read("checksums.json"))
assert "curves.json" in checksums
assert build_audit_inventory(loaded).curve_count == 1
rules_manager.set_package(loaded)
assert rules_manager.audit_curve_count == 1
assert next(
    rules_manager._audit_tree.topLevelItem(index).text(0)
    for index in range(rules_manager._audit_tree.topLevelItemCount())
    if rules_manager._audit_tree.topLevelItem(index).text(0) == "Curves"
) == "Curves"
report = build_report_model(project, results, group_results(results, ()), loaded)
assert report.rules.curve_count == 1
```

Also mutate a curve payload without checksum update and assert load refusal.

- [ ] **Step 2: Run tests and confirm red**

```bash
QT_QPA_PLATFORM=offscreen uv run pytest tests/rules/test_archive.py tests/rules/test_audit.py tests/report/test_model.py tests/ui/test_rules_manager.py -q
```

Expected: FAIL because `curves` and `curves.json` are absent.

- [ ] **Step 3: Implement archive/audit support minimally**

Add `curves: tuple[PiecewiseCurveRule, ...] = ()` to `RulePackage`. Insert `curves.json` into `CORE_MEMBERS`, `_core_member_payloads`, and `load_rule_package`. Extend validation for unique curve IDs/selectors and typed source links. Add curve ownership to `AuditInventory`, audit-tree population, and report count. Keep raw geometry and `SemanticProposal` absent from archive payloads.

Core additions:

```python
class RulePackage(FrozenModel):
    # existing final collections remain
    curves: tuple[PiecewiseCurveRule, ...] = ()

CORE_MEMBERS = (
    "manifest.json", "tables.json", "formulas.json", "mappings.json",
    "decisions.json", "procedures.json", "guidance.json", "curves.json",
)

class AuditInventory(FrozenModel):
    # existing fields remain
    curves: tuple[PiecewiseCurveRule, ...]

class RulesProvenance(FrozenModel):
    # existing fields remain
    curve_count: int
```

- [ ] **Step 4: Run focused tests and confirm green**

```bash
QT_QPA_PLATFORM=offscreen uv run pytest tests/rules/test_archive.py tests/rules/test_audit.py tests/report/test_model.py tests/ui/test_rules_manager.py -q
```

Expected: PASS.

- [ ] **Step 5: Run C1 gate**

```bash
uv run ruff check .
uv run mypy
QT_QPA_PLATFORM=offscreen uv run pytest -n auto --cov=insulation_coordination --cov-branch --cov-report=term-missing --cov-fail-under=80
```

Expected: all exit 0; branch coverage at least 80%.

- [ ] **Step 6: Commit and prepare C1 PR**

```bash
git add src/insulation_coordination tests
git commit -m "feat(rules): archive and audit curve rules"
```

Open PR C1 with `Refs #34`. Do not use `Closes #34`.

---

## PR C2 — Structured DVC extraction

Start C2 from merged C1. PR title: `IEC 62477 Slice C2: structured DVC extraction`. PR body trailer: `Refs #34`.

### Task 6: Compound Table 7 quantities and TOV preservation

**Files:**
- Modify: `src/insulation_coordination/rules/importer/identify.py`
- Modify: `src/insulation_coordination/rules/importer/extract.py`
- Modify: `src/insulation_coordination/rules/importer/projection.py`
- Modify: `src/insulation_coordination/rules/importer/review.py`
- Modify: `src/insulation_coordination/rules/importer/approval.py`
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/tables.py`
- Modify: `src/insulation_coordination/ui/raw_grid_review.py`
- Test: `tests/rules/test_compound_cells.py`
- Test: `tests/rules/importer/iec62477_2022/test_table7_tov_projection.py`
- Test: `tests/ui/test_raw_grid_review.py`

**Interfaces:**
- Consumes: `TableAuditSpec`, `RawGrid`, `RawGridCell`, `Quantity`, existing Table 7 recipe and review corrections.
- Produces: `CompoundQuantitySpec(component_ids: tuple[Identifier, ...])`; `RawQuantityComponent`; `ComponentFormulaCandidate`; `ParsedDataCell.components`; `RawGridCell.components`; `parse_compound_data_cell`; component/formula review corrections; separate AC/DC and impulse/TOV semantic outputs.

- [ ] **Step 1: Write failing compound-cell tests**

Use an unrelated synthetic cell, `"11 ac / 17 dc"`, and an injected neutral component grammar. Assert exact order and source retention:

```python
parsed = parse_compound_data_cell(
    text="11 ac / 17 dc",
    spec=CompoundQuantitySpec(component_ids=("ac", "dc")),
    source=SYNTHETIC_SOURCE,
)
assert [(part.component_id, part.value) for part in parsed.components] == [
    ("ac", Decimal("11")),
    ("dc", Decimal("17")),
]
```

Add named tests asserting: the resulting `RawGridCell.raw_text` remains
`"11 ac / 17 dc"`; reversed labels preserve semantic association; missing label creates
blocking `AMBIGUOUS_COMPOUND_CELL`; correction changes only chosen component and records
provenance; Table 7 projection produces distinct AC/DC routes; an impulse component never
becomes TOV; a TOV component never becomes impulse; ambiguous formula association creates
blocking `AMBIGUOUS_COMPONENT_FORMULA`; reviewer correction selects an exact formula candidate,
changes the proposal hash, and allows review.

- [ ] **Step 2: Run tests and confirm red**

```bash
QT_QPA_PLATFORM=offscreen uv run pytest tests/rules/test_compound_cells.py tests/rules/importer/iec62477_2022/test_table7_tov_projection.py tests/ui/test_raw_grid_review.py -q
```

Expected: FAIL because component types/parser/review UI do not exist.

- [ ] **Step 3: Implement compound parsing minimally**

Define `CompoundQuantitySpec` in `identify.py` and raw component types/parser in `extract.py`:

```python
class CompoundQuantitySpec(FrozenModel):
    component_ids: tuple[Identifier, ...]

class RawQuantityComponent(FrozenModel):
    component_id: Identifier
    raw_text: str
    value: DecimalValue | None = None
    unit: Identifier | None = None
    source: SourceReference

class ComponentFormulaCandidate(FrozenModel):
    component_id: Identifier
    formula_id: Identifier | None
    source: SourceReference

class ParsedDataCell(FrozenModel):
    # existing scalar fields remain
    components: tuple[RawQuantityComponent, ...] = ()
```

Implement `parse_compound_data_cell(text: str, spec: CompoundQuantitySpec,
source: SourceReference) -> ParsedDataCell`. Keep `RawGridCell.raw_text`; attach ordered
`components`. Parser accepts only recipe-declared component IDs and exact extracted labels.
Missing, duplicated, or conflicting association emits a blocking review item; it never guesses
by position. Raw-grid UI shows one editable row per component. Projection routes reviewed Table 7
components into separate semantic families and preserves existing impulse/TOV distinctions.
Zero or multiple formula candidates emit `AMBIGUOUS_COMPONENT_FORMULA`; correction must choose
one exact formula ID before the affected proposal can be reviewed.

- [ ] **Step 4: Run focused tests and confirm green**

```bash
QT_QPA_PLATFORM=offscreen uv run pytest tests/rules/test_compound_cells.py tests/rules/importer/iec62477_2022/test_table7_tov_projection.py tests/ui/test_raw_grid_review.py -q
```

Expected: PASS.

- [ ] **Step 5: Run neighboring tests**

```bash
QT_QPA_PLATFORM=offscreen uv run pytest tests/rules/test_importer.py tests/rules/importer/iec62477_2022 tests/ui/test_rules_manager_review.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/rules/importer src/insulation_coordination/ui/raw_grid_review.py tests/rules/test_compound_cells.py tests/rules/importer/iec62477_2022 tests/ui/test_raw_grid_review.py
git commit -m "feat(importer): separate compound TOV quantities"
```

### Task 7: Table 2 DVC voltage-limit projection and semantic references

**Files:**
- Modify: `src/insulation_coordination/rules/importer/identify.py`
- Modify: `src/insulation_coordination/rules/importer/extract.py`
- Modify: `src/insulation_coordination/rules/importer/review.py`
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/tables.py`
- Create: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/projection.py`
- Test: `tests/rules/importer/iec62477_2022/test_table2_extraction.py`
- Test: `tests/rules/importer/iec62477_2022/test_table2_projection.py`

**Interfaces:**
- Consumes: reviewed `RawGrid`, schema-v4 provenance, `DecisionRule`, `SemanticProposal`, Table 7 semantic IDs, `iec62477_2022.dvc.fault_time_voltage`.
- Produces: `MergedCellSpec`; `BlankCellSemantics`; `SemanticReferenceToken`; `project_dvc_voltage_limits(grid, identity) -> tuple[DecisionRule, tuple[SemanticProposal, ...]]`.

- [ ] **Step 1: Write failing Table 2 tests**

Build an 8×6 synthetic log-independent grid with unrelated numeric values and neutral tokens `CURVE_REF` and `TOV_REF`. Assert:

```python
rules, proposals = project_dvc_voltage_limits(grid, synthetic_identity())
references = {
    output.reference
    for rule in rules
    for row in rule.rows
    for output in row.values
    if output.reference is not None
}
assert "iec62477_2022.dvc.fault_time_voltage" in references
assert any(reference.startswith("iec62477_2022.dvc.tov.") for reference in references)
assert all(proposal.state == "proposed" for proposal in proposals)
```

Also assert merged headers expand deterministically; recipe-declared meaningful blanks differ from missing cells; a figure reference yields no copied curve value; an unresolved neutral token blocks projection; every output has page/table/row/column provenance.
Assert conditional alternative rows use `Matcher.boolean` and evaluate differently for `True`
and `False`; no categorical string surrogate is allowed.

- [ ] **Step 2: Run tests and confirm red**

```bash
uv run pytest tests/rules/importer/iec62477_2022/test_table2_extraction.py tests/rules/importer/iec62477_2022/test_table2_projection.py -q
```

Expected: FAIL because Table 2 recipe/projection and semantic reference tokens do not exist.

- [ ] **Step 3: Implement Table 2 recipe/projection minimally**

Define recipe types in `identify.py` and extracted reference token in `extract.py`:

```python
BlankCellSemantics = Literal["inherit", "not_applicable", "reference", "missing"]

class MergedCellSpec(FrozenModel):
    row: int
    column: int
    row_span: int = Field(ge=1)
    column_span: int = Field(ge=1)
    inherit: Literal["right", "down", "both", "none"]

class BlankCellSpec(FrozenModel):
    row: int
    column: int
    semantics: BlankCellSemantics

class ReferenceSlotSpec(FrozenModel):
    row: int
    column: int
    target_rule_id: Identifier
    target_kind: RuleKind

class SemanticReferenceToken(FrozenModel):
    target_rule_id: Identifier
    target_kind: RuleKind
    source: SourceReference
```

Extend `TableAuditSpec` with default-empty `merged_cells`, `blank_cells`, and `reference_slots`.
Declare only structural locator data in the public recipe: PDF page 44, bbox
`(70.9, 314.5, 524.4, 663.2)`, expected shape 8×6, merged-cell layout, blank semantics, and
reference slots. Never add extracted cell text or values. `project_dvc_voltage_limits` accepts
only a reviewed grid, converts numeric cells to typed quantities, converts Figure 5–7 reference
slots to the single fault-time-voltage semantic ID, converts Table 7 slots to Table 7 semantic
IDs, and emits proposed decision rules with typed provenance.

- [ ] **Step 4: Run focused tests and confirm green**

```bash
uv run pytest tests/rules/importer/iec62477_2022/test_table2_extraction.py tests/rules/importer/iec62477_2022/test_table2_projection.py -q
```

Expected: PASS.

- [ ] **Step 5: Run neighboring tests**

```bash
uv run pytest tests/rules/test_decision_rules.py tests/rules/test_semantic_proposals.py tests/rules/importer/iec62477_2022/test_table7_tov_projection.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/rules/importer/identify.py src/insulation_coordination/rules/importer/extract.py src/insulation_coordination/rules/importer/review.py src/insulation_coordination/rules/importer/recipes/iec62477_1_2022 tests/rules/importer/iec62477_2022
git commit -m "feat(importer): project DVC voltage limits"
```

### Task 8: Table 3 DVC protection matrix projection

**Files:**
- Modify: `src/insulation_coordination/rules/importer/identify.py`
- Modify: `src/insulation_coordination/rules/importer/extract.py`
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/tables.py`
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/projection.py`
- Test: `tests/rules/importer/iec62477_2022/test_table3_extraction.py`
- Test: `tests/rules/importer/iec62477_2022/test_table3_projection.py`

**Interfaces:**
- Consumes: reviewed Table 3 `RawGrid`, boolean decision support from Task 2, typed provenance, semantic proposals.
- Produces: `ProtectionOutcome`; `project_dvc_protection_matrix(grid, identity) -> tuple[DecisionRule, tuple[SemanticProposal, ...]]` with categorical/boolean inputs and typed protection outputs.

- [ ] **Step 1: Write failing Table 3 tests**

Build a 9×7 synthetic grid using neutral categories and yes/no cells. Assert projected rules contain boolean inputs, both boolean match values, exhaustive mixed categorical/boolean products, typed outputs, and source row/column provenance:

```python
rules, proposals = project_dvc_protection_matrix(grid, synthetic_identity())
boolean_match_values = {
    matcher.boolean
    for rule in rules
    for row in rule.rows
    for matcher in row.matchers
    if matcher.boolean is not None
}
assert boolean_match_values == {False, True}
assert {proposal.semantic_id for proposal in proposals} == {rule.id for rule in rules}
```

Add a mutation test that deletes one boolean row and asserts exhaustive-rule validation fails.

- [ ] **Step 2: Run tests and confirm red**

```bash
uv run pytest tests/rules/importer/iec62477_2022/test_table3_extraction.py tests/rules/importer/iec62477_2022/test_table3_projection.py -q
```

Expected: FAIL because Table 3 recipe/projection do not exist.

- [ ] **Step 3: Implement Table 3 recipe/projection minimally**

In IEC `projection.py`, define:

```python
class ProtectionOutcome(FrozenModel):
    category: Identifier
    evidence_required: bool
    applicable: bool
    source: SourceReference
```

Declare only PDF page 45, bbox `(71.0, 265.3, 524.3, 744.2)`, expected shape 9×7, merge structure, and neutral token grammar. Convert reviewed yes/no tokens to real booleans. Project `ProtectionOutcome` fields to typed `DecisionValue` outputs, not display text. Reject unknown tokens and incomplete Cartesian coverage with blocking review items.

- [ ] **Step 4: Run focused tests and confirm green**

```bash
uv run pytest tests/rules/importer/iec62477_2022/test_table3_extraction.py tests/rules/importer/iec62477_2022/test_table3_projection.py -q
```

Expected: PASS.

- [ ] **Step 5: Run neighboring tests**

```bash
uv run pytest tests/rules/test_decision_rules.py tests/rules/test_decision_evaluation.py tests/rules/importer/iec62477_2022/test_table2_projection.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/rules/importer/identify.py src/insulation_coordination/rules/importer/extract.py src/insulation_coordination/rules/importer/recipes/iec62477_1_2022 tests/rules/importer/iec62477_2022
git commit -m "feat(importer): project DVC protection matrix"
```

### Task 9: Generic clause fragments and DVC applicability decisions

**Files:**
- Modify: `src/insulation_coordination/rules/importer/identify.py`
- Create: `src/insulation_coordination/rules/importer/clauses.py`
- Modify: `src/insulation_coordination/rules/importer/extract.py`
- Modify: `src/insulation_coordination/rules/importer/review.py`
- Modify: `src/insulation_coordination/rules/importer/approval.py`
- Create: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/clauses.py`
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/__init__.py`
- Test: `tests/rules/test_clause_extraction.py`
- Test: `tests/rules/importer/iec62477_2022/test_dvc_clause_projection.py`

**Interfaces:**
- Consumes: `StandardRecipe`, page text/chars from pdfplumber, typed source provenance, `DecisionRule`, semantic proposals.
- Produces: `ClauseAuditSpec`; `ClauseNode`; `ClauseToken`; `RawClauseFragment`; `extract_clause_fragment`; `normalize_clause_fragment`; `project_dvc_fault_applicability(fragment, identity) -> tuple[DecisionRule, tuple[SemanticProposal, ...]]`.

- [ ] **Step 1: Write failing clause tests**

Create a synthetic two-column page fragment with neutral clause identifiers and tokens. Assert extraction respects bbox/reading order, normalization preserves token spans and source boxes, projection consumes only reviewed tokens, and ambiguity blocks:

```python
fragment = extract_clause_fragment(page, synthetic_clause_spec())
assert [node.order for node in fragment.nodes] == list(range(len(fragment.nodes)))
assert all(token.source.page == 3 for token in fragment.tokens)
assert normalize_clause_fragment(fragment).raw_sha256 == fragment.raw_sha256
```

Add projection assertions for typed applicability inputs/outputs and a mutation that swaps two neutral tokens and changes the canonical rule hash.

- [ ] **Step 2: Run tests and confirm red**

```bash
uv run pytest tests/rules/test_clause_extraction.py tests/rules/importer/iec62477_2022/test_dvc_clause_projection.py -q
```

Expected: FAIL because clause recipes/extraction/projection do not exist.

- [ ] **Step 3: Implement clause pipeline minimally**

Define exact clause shapes:

```python
class ClauseAuditSpec(FrozenModel):
    semantic_id: Identifier
    clause: ReferenceText
    page_number: int = Field(ge=1)
    expected_bbox: tuple[float, float, float, float]
    expected_root_kind: Literal["paragraph", "bullets"]
    output_kind: Literal["decision", "procedure"]

class ClauseNode(FrozenModel):
    order: int = Field(ge=0)
    kind: Literal["paragraph", "bullet", "alternative"]
    raw_text: str
    source: SourceReference

class ClauseToken(FrozenModel):
    kind: Literal["reference", "quantity", "unit", "operator", "condition"]
    raw_text: str
    normalized: str | Decimal
    source: SourceReference

class RawClauseFragment(FrozenModel):
    id: Identifier
    raw_sha256: str
    nodes: tuple[ClauseNode, ...]
    tokens: tuple[ClauseToken, ...]
    source: SourceReference
```

Define `ClauseAuditSpec` in `identify.py`; define `ClauseNode`, `ClauseToken`,
`RawClauseFragment`, extraction, and normalization in `clauses.py`. Add
`clauses: tuple[ClauseAuditSpec, ...] = ()` to `StandardRecipe`. Extract only recipe bbox and
declared clause identifier. Store private raw fragments and token geometry; public recipe stores
no licensed wording. Normalizer merges wrapped lines deterministically and preserves ordered
source spans. IEC projection maps reviewed neutral token roles to applicability decisions;
unknown structure creates blocking `AMBIGUOUS_CLAUSE_STRUCTURE`.

- [ ] **Step 4: Run focused tests and confirm green**

```bash
uv run pytest tests/rules/test_clause_extraction.py tests/rules/importer/iec62477_2022/test_dvc_clause_projection.py -q
```

Expected: PASS.

- [ ] **Step 5: Run neighboring tests**

```bash
uv run pytest tests/rules/test_importer.py tests/rules/test_semantic_proposals.py tests/rules/importer/iec62477_2022/test_table2_projection.py tests/rules/importer/iec62477_2022/test_table3_projection.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/rules/importer tests/rules/test_clause_extraction.py tests/rules/importer/iec62477_2022
git commit -m "feat(importer): extract structured clause decisions"
```

### Task 10: Semantic review UI, C2 review gate, and private DVC verification

**Files:**
- Create: `src/insulation_coordination/ui/semantic_review.py`
- Modify: `src/insulation_coordination/ui/rules_manager.py`
- Modify: `src/insulation_coordination/rules/importer/review.py`
- Modify: `src/insulation_coordination/rules/importer/approval.py`
- Test: `tests/ui/test_semantic_review.py`
- Test: `tests/ui/test_rules_manager_review.py`
- Test: `tests/private/test_iec62477_dvc_tables.py`

**Interfaces:**
- Consumes: `SemanticProposal`, reviewed raw grids/clause fragments, `mark_proposal_reviewed`, `approve_draft`, ignored private-standard fixture.
- Produces: `SemanticReviewModel`; rule/hash/source presentation; correction actions for cell/component/token association; reviewed-state action; C2 review-completeness gate while final package approval remains blocked on C3 curves.

- [ ] **Step 1: Write failing UI/private tests**

Public UI tests use synthetic proposals and assert proposed rules cannot approve, correction changes hash and resets review, a complete synthetic dependency set enables approval, source jump uses typed page/bbox, and every rule kind is visible. Private C2 test reviews all C2 proposals but asserts final IEC approval remains blocked by missing `iec62477_2022.dvc.fault_time_voltage`. It uses only structural assertions:

```python
grids = {grid.id: grid for grid in draft.raw_grids}
assert (grids["iec62477_2022.dvc.voltage_limits"].rows, grids["iec62477_2022.dvc.voltage_limits"].columns) == (8, 6)
assert (grids["iec62477_2022.dvc.protection_matrix"].rows, grids["iec62477_2022.dvc.protection_matrix"].columns) == (9, 7)
assert all(proposal.state == "proposed" for proposal in draft.semantic_proposals)
assert [
    (item.semantic_id, item.rule_sha256, item.source_artifact_sha256)
    for item in first.semantic_proposals
] == [
    (item.semantic_id, item.rule_sha256, item.source_artifact_sha256)
    for item in second.semantic_proposals
]
with pytest.raises(ApprovalError, match="fault_time_voltage"):
    approve_draft(review_all_c2_proposals(first), synthetic_approval())
```

Private test must derive actual values from licensed PDF at runtime and must not assert, snapshot, print, or serialize them into repository artifacts.

- [ ] **Step 2: Run public tests and confirm red**

```bash
QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_semantic_review.py tests/ui/test_rules_manager_review.py -q
```

Expected: FAIL because semantic-review model/UI do not exist.

- [ ] **Step 3: Implement semantic review minimally**

Define `SemanticReviewModel(draft: ImportedRuleDraft)` with `proposal(semantic_id)`,
`correct(semantic_id, correction)`, `review(semantic_id, actor, notes)`, and
`can_approve: bool`. Back one view with existing Rule Manager selection. Show semantic ID, kind,
state, current canonical hash, linked page/bbox, and structured inputs/outputs. Reuse existing
correction records. `review` calls `mark_proposal_reviewed`; `can_approve` remains false while
any required proposal or review item blocks. For actual C2 IEC drafts, missing C3 curve remains a
blocker; C2 merge criterion is review completeness, not final package construction. Do not cache
licensed text or values in settings/logs.

Core delegation:

```python
class SemanticReviewModel:
    def review(self, semantic_id: str, actor: str, notes: str) -> ImportedRuleDraft:
        self.draft = mark_proposal_reviewed(
            self.draft, semantic_id, actor=actor, notes=notes
        )
        return self.draft

    @property
    def can_approve(self) -> bool:
        return not approval_blockers(self.draft)
```

- [ ] **Step 4: Run focused public and private tests**

```bash
QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_semantic_review.py tests/ui/test_rules_manager_review.py -q
uv run pytest -m private_standard tests/private/test_iec62477_dvc_tables.py -q
```

Expected: both commands PASS on maintainer machine; private command SKIP with explicit missing-fixture reason elsewhere.

- [ ] **Step 5: Run C2 gate**

```bash
uv run ruff check .
uv run mypy
QT_QPA_PLATFORM=offscreen uv run pytest -n auto --cov=insulation_coordination --cov-branch --cov-report=term-missing --cov-fail-under=80
uv run pytest -m private_standard tests/private/test_iec62477_dvc_tables.py -q
```

Expected: all commands exit 0 on maintainer machine; branch coverage at least 80%.

- [ ] **Step 6: Commit and prepare C2 PR**

```bash
git add src/insulation_coordination/ui/semantic_review.py src/insulation_coordination/ui/rules_manager.py src/insulation_coordination/rules/importer/review.py src/insulation_coordination/rules/importer/approval.py tests/ui/test_semantic_review.py tests/ui/test_rules_manager_review.py tests/private/test_iec62477_dvc_tables.py
git commit -m "feat(ui): review DVC semantic proposals"
```

Open PR C2 with `Refs #34`. Do not use `Closes #34`.

---

## PR C3 — Automatic Figure 5–7 digitization

Start C3 from merged C2. PR title: `IEC 62477 Slice C3: reviewed Figure 5–7 digitization`. PR body trailer: `Refs #34`.

### Task 11: OCR protocol, deterministic Tesseract adapter, and explicit image dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `src/insulation_coordination/rules/importer/curves.py`
- Test: `tests/rules/test_curve_ocr.py`

**Interfaces:**
- Consumes: Pillow `>=12,<13`, stdlib `subprocess.run`, `Path`, `Decimal`, typed source geometry.
- Produces: `PixelBox`; `OcrToken`; `OcrEngineIdentity`; runtime-checkable `OcrEngine` protocol; `TesseractOcrEngine.recognize(image: Image.Image) -> tuple[OcrToken, ...]`; test `FakeOcrEngine`.

- [ ] **Step 1: Write failing OCR contract tests**

```python
class FakeOcrEngine:
    identity = OcrEngineIdentity(name="fake", version="1", config_sha256="0" * 64)

    def recognize(self, image: Image.Image) -> tuple[OcrToken, ...]:
        return (OcrToken(text="13", confidence=Decimal("0.99"), box=PixelBox(1, 2, 3, 4)),)

def test_fake_ocr_is_protocol_compatible() -> None:
    assert isinstance(FakeOcrEngine(), OcrEngine)
```

Mock `subprocess.run` and assert fixed argv, `shell=False`, timeout, UTF-8 TSV parsing, deterministic token order, non-zero exit as blocking `OCR_FAILED`, and missing executable as blocking `OCR_UNAVAILABLE`. No public test invokes installed Tesseract.

- [ ] **Step 2: Run tests and confirm red**

```bash
uv run pytest tests/rules/test_curve_ocr.py -q
```

Expected: FAIL because OCR interfaces/adapter do not exist.

- [ ] **Step 3: Implement OCR boundary minimally**

Add exact boundary types in `curves.py`:

```python
class PixelBox(FrozenModel):
    left: int = Field(ge=0)
    top: int = Field(ge=0)
    right: int = Field(gt=0)
    bottom: int = Field(gt=0)

class OcrToken(FrozenModel):
    text: str
    confidence: Decimal = Field(ge=0, le=1)
    box: PixelBox

class OcrEngineIdentity(FrozenModel):
    name: Identifier
    version: str
    config_sha256: str

@runtime_checkable
class OcrEngine(Protocol):
    @property
    def identity(self) -> OcrEngineIdentity: ...

    def recognize(self, image: Image.Image) -> tuple[OcrToken, ...]: ...
```

Validate ordered `PixelBox` edges and SHA-256. Add explicit `pillow>=12,<13`; do not add OpenCV
or NumPy. Adapter writes one temporary lossless PNG, calls fixed
`tesseract <png> stdout --psm 6 tsv` argv with timeout and `shell=False`, parses TSV by
`(top, left, line_num, word_num)`, deletes temporary file, and returns no source image.
Version/config digest joins source artifact provenance. PySide6 `QImage` remains UI-only.

- [ ] **Step 4: Run focused tests and confirm green**

```bash
uv run pytest tests/rules/test_curve_ocr.py -q
```

Expected: PASS.

- [ ] **Step 5: Run dependency and neighbor checks**

```bash
uv lock --check
uv run pytest tests/rules/test_importer.py tests/rules/test_source_provenance.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/insulation_coordination/rules/importer/curves.py tests/rules/test_curve_ocr.py
git commit -m "feat(importer): abstract local curve OCR"
```

### Task 12: Vector-first source-figure geometry with XObject fallback

**Files:**
- Modify: `src/insulation_coordination/rules/importer/identify.py`
- Modify: `src/insulation_coordination/rules/importer/curves.py`
- Create: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/curves.py`
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/__init__.py`
- Test: `tests/fixtures/synthetic_pdf.py`
- Test: `tests/rules/test_curve_source_extraction.py`
- Test: `tests/rules/importer/iec62477_2022/test_curve_recipe.py`

**Interfaces:**
- Consumes: pypdf content streams/XObjects, pdfplumber page geometry, Pillow, `StandardRecipe`, `OcrEngine`.
- Produces: `CurveAuditSpec`; `StandardRecipe.curves`; `RawCurvePoint`; `RawCurveTrace`; `RawFigure`; `locate_curve_source`; `extract_raw_figure`; source mode `vector_path` or `image_xobject`.

- [ ] **Step 1: Write failing vector/fallback tests**

Extend synthetic PDF fixture with one page containing both vector paths and a lossless image, and another page containing only a lossless image. Assert:

```python
vector = extract_raw_figure(vector_page, synthetic_curve_spec(), FakeOcrEngine())
raster = extract_raw_figure(raster_page, synthetic_curve_spec(), FakeOcrEngine())
assert vector.source_mode == "vector_path"
assert raster.source_mode == "image_xobject"
assert vector.artifact_sha256 == extract_raw_figure(vector_page, synthetic_curve_spec(), FakeOcrEngine()).artifact_sha256
```

Also assert vector data wins even when image exists; lossy/ambiguous image choice blocks; crop bbox and transformation matrix are retained; `RawCurvePoint` carries pixel/PDF geometry while `CurvePoint` does not. IEC recipe test asserts only allowed structural locators: pages 54–56 and figure IDs 5–7.

- [ ] **Step 2: Run tests and confirm red**

```bash
uv run pytest tests/rules/test_curve_source_extraction.py tests/rules/importer/iec62477_2022/test_curve_recipe.py -q
```

Expected: FAIL because curve source models/recipe/extractor do not exist.

- [ ] **Step 3: Implement vector-first extraction minimally**

Define `CurveAuditSpec` in `identify.py` and raw evidence types in `curves.py`:

```python
class CurveAuditSpec(FrozenModel):
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
    variant_slots: tuple[FaultTimeVoltageSelector, ...]
    permitted_segment_types: tuple[CurveSegmentType, ...]
    permitted_interpolations: tuple[CurveInterpolation, ...]

class RawCurvePoint(FrozenModel):
    x: Decimal
    y: Decimal
    space: Literal["pdf", "pixel"]
    primitive_ref: str

class RawCurveTrace(FrozenModel):
    id: Identifier
    points: tuple[RawCurvePoint, ...]
    stroke_width: Decimal

class RawFigure(FrozenModel):
    source: SourceReference
    source_mode: Literal["vector_path", "image_xobject"]
    source_bbox: tuple[Decimal, Decimal, Decimal, Decimal]
    pixel_size: tuple[int, int] | None
    transform: tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]
    ocr_tokens: tuple[OcrToken, ...]
    traces: tuple[RawCurveTrace, ...]
    artifact_sha256: str
```

Add `curves: tuple[CurveAuditSpec, ...] = ()` to `StandardRecipe`. Inspect content-stream path operators inside recipe bbox first. Use them when a deterministic candidate set exists. Otherwise decode the single recipe-matching lossless image XObject and its PDF transform. Multiple candidates, unsupported filters, clipping uncertainty, or incomplete transforms emit blocking review items. Hash decoded source bytes plus transform/spec/OCR identity. Never write image bytes under repository paths or into final package.

- [ ] **Step 4: Run focused tests and confirm green**

```bash
uv run pytest tests/rules/test_curve_source_extraction.py tests/rules/importer/iec62477_2022/test_curve_recipe.py -q
```

Expected: PASS.

- [ ] **Step 5: Run neighboring tests**

```bash
uv run pytest tests/rules/test_curve_ocr.py tests/rules/test_source_provenance.py tests/rules/test_importer.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/rules/importer/identify.py src/insulation_coordination/rules/importer/curves.py src/insulation_coordination/rules/importer/recipes/iec62477_1_2022 tests/fixtures/synthetic_pdf.py tests/rules/test_curve_source_extraction.py tests/rules/importer/iec62477_2022/test_curve_recipe.py
git commit -m "feat(importer): extract source figure geometry"
```

### Task 13: Log-axis calibration and provably conservative reconstruction

**Files:**
- Modify: `src/insulation_coordination/rules/importer/curves.py`
- Test: `tests/rules/test_log_curve_digitization.py`
- Test: `tests/rules/test_conservative_curves.py`

**Interfaces:**
- Consumes: `RawFigure`, `RawCurveTrace`, `RawCurvePoint`, OCR ticks, schema-v4 curve models.
- Produces: `AxisCalibration`; `PlotCalibration`; `ConservatismReport`; `CurveDigitizationResult`; `calibrate_log_axis`; `trace_curves`; `conservative_simplify`; `prove_conservative`; `digitize_curve_figure`; deterministic proposed `PiecewiseCurveRule`.

- [ ] **Step 1: Write failing log/calibration/conservatism tests**

Generate a synthetic log-log chart at test time with Pillow, unrelated axes, two strokes, known thickness, and injected OCR tokens. Assert:

```python
first = digitize_synthetic_chart(image, FakeOcrEngine(tokens))
second = digitize_synthetic_chart(image, FakeOcrEngine(tokens))
assert first.proposed_rule is not None
assert second.proposed_rule is not None
assert first.calibration is not None
assert first.conservatism is not None
assert canonical_model_sha256(first.proposed_rule) == canonical_model_sha256(second.proposed_rule)
assert first.calibration.x.scale == "log10"
assert first.calibration.y.scale == "log10"
assert first.conservatism.maximum_positive_voltage_error <= Decimal("0")
```

Add exact failures: fewer than two valid ticks; non-monotone tick mapping; residual above half minor-grid spacing; disconnected/branching stroke; curve crossings with unresolved association; candidate segment above lower uncertainty envelope at any source column, breakpoint, or analytic segment/envelope intersection; requested x outside explicit domain. Assert conservative rounding moves time outward and voltage downward, never opposite.

- [ ] **Step 2: Run tests and confirm red**

```bash
uv run pytest tests/rules/test_log_curve_digitization.py tests/rules/test_conservative_curves.py -q
```

Expected: FAIL because calibration/tracing/conservatism functions do not exist.

- [ ] **Step 3: Implement deterministic conservative pipeline minimally**

Define:

```python
class AxisCalibration(FrozenModel):
    scale: Literal["log10"]
    slope: Decimal
    intercept: Decimal
    residual_pixels: Decimal
    minor_grid_spacing_pixels: Decimal

class PlotCalibration(FrozenModel):
    x: AxisCalibration
    y: AxisCalibration

class ConservatismReport(FrozenModel):
    maximum_positive_voltage_error: Decimal
    maximum_fidelity_error_pixels: Decimal
    proven: bool

class CurveDigitizationResult(FrozenModel):
    proposed_rule: PiecewiseCurveRule | None
    calibration: PlotCalibration | None
    conservatism: ConservatismReport | None
    blocking_review_items: tuple[ImportReviewItem, ...]
```

Successful `CurveDigitizationResult` has proposal/calibration/proof and no blocker. A failed
stage leaves its later optional fields `None` and carries blocking review items. The public test helper
`digitize_synthetic_chart` delegates to `digitize_curve_figure` with a synthetic
`CurveAuditSpec`.

Fit each axis in `log10(value) = a * pixel + b` space using declared ticks. Require monotonicity and residual no greater than half detected minor-grid spacing. Build each stroke uncertainty band from detected stroke width; use `max(1 pixel, ceil(stroke_width / 2))` as fidelity tolerance. For a maximum-voltage rule, choose lower-voltage boundary at every sampled column, choose earliest time at descending transitions, and round `Decimal` time outward/voltage downward at declared precision. Simplify only when `prove_conservative` checks every source column, breakpoint, and analytic segment/envelope intersection. Any failed proof returns blocking `CURVE_CONSERVATISM_UNPROVEN`; it never returns a semantic curve. Never extend beyond explicit traced endpoints.

- [ ] **Step 4: Run focused tests and confirm green**

```bash
uv run pytest tests/rules/test_log_curve_digitization.py tests/rules/test_conservative_curves.py -q
```

Expected: PASS.

- [ ] **Step 5: Run neighboring tests**

```bash
uv run pytest tests/rules/test_curve_ocr.py tests/rules/test_curve_source_extraction.py tests/rules/test_piecewise_curves.py tests/rules/test_curve_evaluation.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/rules/importer/curves.py tests/rules/test_log_curve_digitization.py tests/rules/test_conservative_curves.py
git commit -m "feat(importer): digitize conservative log curves"
```

### Task 14: Figure 5–7 semantic association and local overlay review

**Files:**
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/curves.py`
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/__init__.py`
- Modify: `src/insulation_coordination/rules/importer/extract.py`
- Modify: `src/insulation_coordination/rules/importer/projection.py`
- Modify: `src/insulation_coordination/rules/importer/review.py`
- Modify: `src/insulation_coordination/rules/importer/approval.py`
- Create: `src/insulation_coordination/ui/curve_review.py`
- Modify: `src/insulation_coordination/ui/rules_manager.py`
- Test: `tests/rules/importer/iec62477_2022/test_figure_curve_proposals.py`
- Test: `tests/ui/test_curve_review.py`

**Interfaces:**
- Consumes: C3 raw figures/calibration/traces, `SemanticProposal`, schema-v4 exact selectors, typed provenance, local source-document path held outside package.
- Produces: `ImportedRuleDraft.raw_figures`; `ImportedRuleDraft.curve_digitizations`; `project_fault_time_voltage`; `correct_curve_calibration`; `associate_curve_trace`; `replace_curve_breakpoint`; `replace_curve_segment`; `CurveReviewModel`; local QImage/QGraphicsPath overlay; manual-point fallback after a blocking extraction result.

- [ ] **Step 1: Write failing proposal/UI tests**

Use synthetic figures only. Assert all proposed variants are distinguishable by exact selector and remain proposed:

```python
rule = next(rule for rule in draft.curves if rule.id == proposal.semantic_id)
selectors = {variant.selector for variant in rule.variants}
assert len(selectors) == len(rule.variants)
assert proposal.semantic_id == "iec62477_2022.dvc.fault_time_voltage"
assert proposal.state == "proposed"
assert approve_button.isEnabled() is False
```

Cover selector meanings: accessible circuit vs conductive accessible part; AC/DC/AC-peak; applicable DVC/environment dimensions. Assert exact `None` dimensions do not wildcard. UI tests assert source image loads from current local PDF, overlay maps semantic points back through calibration, changing a breakpoint/association/segment type/interpolation changes rule hash and resets review, accepting records exact artifact/rule hashes, and manual entry is unavailable until automatic extraction has a blocking failure or maintainer rejection.

- [ ] **Step 2: Run tests and confirm red**

```bash
QT_QPA_PLATFORM=offscreen uv run pytest tests/rules/importer/iec62477_2022/test_figure_curve_proposals.py tests/ui/test_curve_review.py -q
```

Expected: FAIL because IEC projection/curve review UI do not exist.

- [ ] **Step 3: Implement proposal and overlay review minimally**

Define `CurveReviewModel` methods `set_calibration(axis, calibration)`,
`associate_trace(trace_id, variant_slot)`, `set_breakpoint(variant_id, index, point)`,
`set_segment(variant_id, index, start, end, segment_type, interpolation)`, and
`review_variant(variant_id, actor, notes)`. Each mutation re-runs conservatism and proposal hashing.

Add draft-only `raw_figures: tuple[RawFigure, ...] = ()` and
`curve_digitizations: tuple[CurveDigitizationResult, ...] = ()` to `ImportedRuleDraft`. Approval
drops both. They contain hashes/geometry but no image bytes; Curve Review reopens the current local
PDF, verifies its manifest SHA-256, then decodes the crop in memory.

UI methods delegate to review functions so every mutation records a correction and resets the
aggregate proposal:

```python
def set_segment(
    self,
    variant_id: str,
    index: int,
    start: int,
    end: int,
    segment_type: CurveSegmentType,
    interpolation: CurveInterpolation,
) -> ImportedRuleDraft:
    self.draft = replace_curve_segment(
        self.draft,
        variant_id=variant_id,
        index=index,
        segment=CurveSegment(
            start=start,
            end=end,
            segment_type=segment_type,
            interpolation=interpolation,
        ),
    )
    return self.draft
```

Public IEC recipe stores only figure/page/bbox/image-dimension locators and typed selector role definitions, never extracted labels or values. `project_fault_time_voltage` creates one proposed rule under `iec62477_2022.dvc.fault_time_voltage`; every variant has exact four-dimension selector, breakpoints, segments, interpolation, applicability, source, and reviewed-artifact link. Figures 5/6 use `subject="accessible_circuit"`; Figure 7 uses `subject="conductive_accessible_part"` and explicit `None` for inapplicable DVC/environment dimensions. Curve Review renders local licensed crop through `QImage`, semantic reconstruction through `QGraphicsPathItem`, and never persists pixels. Corrections regenerate canonical hashes. Proposal artifact hash covers the ordered Figure 5–7 artifact digests; only exact per-variant reviews plus matching aggregate rule/artifact hashes clear blockers.

- [ ] **Step 4: Run focused tests and confirm green**

```bash
QT_QPA_PLATFORM=offscreen uv run pytest tests/rules/importer/iec62477_2022/test_figure_curve_proposals.py tests/ui/test_curve_review.py -q
```

Expected: PASS.

- [ ] **Step 5: Run neighboring tests**

```bash
QT_QPA_PLATFORM=offscreen uv run pytest tests/rules/test_semantic_proposals.py tests/rules/test_curve_evaluation.py tests/ui/test_semantic_review.py tests/ui/test_rules_manager_review.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/rules/importer src/insulation_coordination/ui/curve_review.py src/insulation_coordination/ui/rules_manager.py tests/rules/importer/iec62477_2022/test_figure_curve_proposals.py tests/ui/test_curve_review.py
git commit -m "feat(ui): review reconstructed IEC curves"
```

### Task 15: Slice C reference resolution, private round trip, and final gates

**Files:**
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/projection.py`
- Modify: `src/insulation_coordination/rules/importer/approval.py`
- Modify: `src/insulation_coordination/rules/archive.py`
- Modify: `src/insulation_coordination/rules/validation.py`
- Test: `tests/rules/importer/iec62477_2022/test_slice_c_integration.py`
- Test: `tests/private/test_iec62477_curves.py`
- Test: `tests/private/test_iec62477_slice_c_roundtrip.py`

**Interfaces:**
- Consumes: approved DVC/Table 7 decisions, approved fault-time-voltage curve, archive round trip, `select_curve_variant`, `evaluate_piecewise_curve`, ignored licensed PDF fixture.
- Produces: resolved Table 2 semantic references; private structural/determinism/review/round-trip/API proof; final Slice C quality gate.

- [ ] **Step 1: Write failing public/private integration tests**

Public synthetic test asserts reference identity, not values:

```python
package = approve_synthetic_slice_c(review_all(synthetic_slice_c_draft()))
fault_reference = next(
    value.reference
    for rule in package.decisions
    for row in rule.rows
    for value in row.values
    if value.reference == "iec62477_2022.dvc.fault_time_voltage"
)
curve_by_id = {curve.id: curve for curve in package.curves}
assert curve_by_id[fault_reference] is package.curves[0]
path = tmp_path / "synthetic.icrules"
write_rule_package(path, package)
reloaded = load_rule_package(path)
assert reloaded.curves == package.curves
assert evaluate_piecewise_curve(reloaded.curves[0], synthetic_selector(), Decimal("27")).status == "matched"
```

Private tests locate Figures 5, 6, and 7; digitize twice and compare canonical hashes; assert initial proposal blocks approval; review all required exact artifact/rule hashes through review API; export/re-import `.icrules`; evaluate every extracted selector at an in-domain breakpoint; assert Table 2 resolves to the single curve rule and Table 7 semantic IDs. Never assert, snapshot, log, or commit actual labels, coordinates, thresholds, values, crops, or package bytes.

- [ ] **Step 2: Run public test and confirm red**

```bash
uv run pytest tests/rules/importer/iec62477_2022/test_slice_c_integration.py -q
```

Expected: FAIL until reference resolution and complete approved-package wiring exist.

- [ ] **Step 3: Complete integration minimally**

Validation resolves every decision reference to exactly one final rule ID across rule kinds; zero
or multiple targets fail `SEMANTIC_REFERENCES_RESOLVE`. Approval requires every required
Figure 5–7 variant and its current source artifact hash to be reviewed; missing, duplicated,
stale, ambiguous, or out-of-domain variants block. Archive only final semantic curve/provenance
data. Private round-trip test writes packages under pytest `tmp_path`; no repository fixture or
golden is created.

Validation builds one exact semantic-ID index and rejects absent/duplicate targets:

```python
targets: dict[str, list[RuleKind]] = {}
for kind, rules in (
    ("table", package.tables),
    ("formula", package.formulas),
    ("decision", package.decisions),
    ("procedure", package.procedures),
    ("guidance", package.guidance),
    ("curve", package.curves),
):
    for rule in rules:
        targets.setdefault(rule.id, []).append(kind)
for reference in decision_reference_values(package.decisions):
    if len(targets.get(reference, ())) != 1:
        failures.add("SEMANTIC_REFERENCES_RESOLVE")
```

- [ ] **Step 4: Run focused public and private tests**

```bash
uv run pytest tests/rules/importer/iec62477_2022/test_slice_c_integration.py -q
uv run pytest -m private_standard tests/private/test_iec62477_curves.py tests/private/test_iec62477_slice_c_roundtrip.py -q
```

Expected: both commands PASS on maintainer machine; private command SKIP with explicit missing-fixture reason elsewhere.

- [ ] **Step 5: Run final C3 gate and licensed-content scan**

```bash
uv run ruff check .
uv run mypy
QT_QPA_PLATFORM=offscreen uv run pytest -n auto --cov=insulation_coordination --cov-branch --cov-report=term-missing --cov-fail-under=80
uv run pytest -m private_standard tests/private -q
git diff --check origin/main...HEAD
! git diff --name-only origin/main...HEAD | rg '\.(pdf|png|jpg|jpeg|tif|tiff|icrules)$'
```

Expected: all quality commands exit 0; branch coverage at least 80%; artifact scan prints no path. Manually inspect staged diff for licensed literals because filename scanning cannot detect copied text or values.

- [ ] **Step 6: Commit and prepare C3 PR**

```bash
git add src/insulation_coordination tests/rules/importer/iec62477_2022/test_slice_c_integration.py tests/private/test_iec62477_curves.py tests/private/test_iec62477_slice_c_roundtrip.py
git commit -m "test(private): verify IEC 62477 Slice C round trip"
```

Open PR C3 with `Refs #34`. Do not use `Closes #34`; issue closure follows maintainer acceptance of C3.

---

## Definition of Done

- C1 merged: schema v4 provenance, boolean matching, curve semantics/evaluation, proposal lifecycle, archive/audit support.
- C2 merged: Tables 2/3/7 plus relevant clauses extracted into proposed semantic rules; TOV fixes preserved; maintainer review works; final approval correctly remains blocked on C3 curves; private structural tests pass.
- C3 merged: Figures 5–7 automatically located and vector-first digitized with lossless-image fallback; log calibration and conservative proof deterministic; every ambiguity blocks; local overlay/correction/review works; manual entry remains fallback.
- Approved Figure 5–7 curves survive `.icrules` export/re-import and evaluate through semantic API with exact variant selection and no extrapolation.
- Table 2 contains references to `iec62477_2022.dvc.fault_time_voltage` and Table 7 semantic IDs, never copied curve/Table 7 values.
- Public repository contains no licensed IEC literals or artifacts; public curve tests use unrelated synthetic log figures; actual IEC checks stay under `private_standard`.
- Ruff, strict mypy, full branch-aware pytest at 80% minimum coverage, private DVC/curve tests, archive checks, and licensed-artifact scan pass.
- All three PRs say `Refs #34`; issue remains open until C3 maintainer acceptance.

## Execution Order

Implement C1 Tasks 1–5, merge C1, rebase/start C2. Implement C2 Tasks 6–10, merge C2, rebase/start C3. Implement C3 Tasks 11–15. Do not parallel-edit shared importer/domain files across PRs.
