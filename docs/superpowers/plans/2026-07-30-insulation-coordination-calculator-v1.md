# Insulation Coordination Calculator V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline Windows application that calculates auditable functional, basic, and reinforced clearance and creepage requirements from private IEC rule packages and generates LaTeX/PDF insulation-coordination reports.

**Architecture:** A PySide6 desktop shell calls a UI-independent Python domain engine. Versioned `.icproj` JSON files hold project inputs, private `.icrules` ZIP files hold declarative tables/formulas, and every calculation produces an immutable trace consumed by grouping and reporting. Licensed IEC PDFs and extracted values remain local and are never committed.

**Tech Stack:** Python 3.12, PySide6 6.x, Pydantic 2.x, `decimal`, Jinja2 3.x, pypdf/pdfplumber, pytest, Hypothesis, pytest-qt, Ruff, mypy, PyInstaller, pinned offline Tectonic, Inno Setup.

## Global Constraints

- Run completely offline on Windows; runtime code must not make network requests.
- Never commit IEC PDFs, `.icrules`, `.icproj`, rule-audit exports, or extracted IEC values.
- Use synthetic public fixtures; private-standard integration tests must read ignored local files and skip clearly when absent.
- Support functional, basic, and reinforced insulation; supplementary insulation is outside V1.
- Store voltages in volts, frequency in hertz, altitude in metres, and distances/electrode dimensions in millimetres.
- Use `Decimal` for engineering arithmetic; do not use binary floating point in rule evaluation.
- Treat pair cases as unordered and canonical; A-to-B and B-to-A must share one record.
- Resolve project defaults plus visible pair overrides before calculation.
- Do not execute code from `.icrules`; accept only versioned, whitelisted declarative operators.
- Block calculation for missing, unapproved, altered, incompatible, unsupported, or out-of-range rules/inputs.
- Preserve every lookup, formula, substitution, interpolation, correction, rounding step, and exact source reference.
- Final creepage must never be below final clearance.
- Final report generation is blocked while any project pair has a blocking error.
- Generate editable `.tex` and PDF with a pinned compiler/resource bundle.
- Each task follows red-green-refactor, passes Ruff/mypy/pytest for touched code, and ends with a focused commit.

## Planned File Structure

```text
pyproject.toml
uv.lock
src/insulation_coordination/
  __init__.py
  cli.py
  domain/
    enums.py             # insulation, provenance, status, field/construction enums
    quantities.py        # Decimal-backed canonical quantities
    project.py           # project, net-class, pair, defaults/override models
    rules.py             # rule package, table, formula AST, mappings
    trace.py             # trace, warning, blocking error, result models
  project/
    pairs.py             # canonical pair generation and reconciliation
    resolver.py          # defaults + overrides -> effective case
    persistence.py       # .icproj load, migration, atomic save
  rules/
    archive.py           # deterministic .icrules ZIP and checksums
    validation.py        # structural, semantic, approval validation
    audit.py              # full audit inventory and private exports
    evaluator.py          # declarative Decimal formula evaluator
    importer/
      identify.py         # edition/layout identification and source hashing
      extract.py          # draft package orchestration
      approval.py         # draft correction and approval state
      recipes/
        iec60664_1_2020.py
        iec60664_4_2005.py
  calculation/
    engine.py             # pair calculation orchestration
    clearance.py          # Part 1 clearance candidates
    creepage.py           # Part 1 creepage candidates and clearance floor
    high_frequency.py     # Part 4 candidates and bounded iteration
    grouping.py           # deterministic signature and safe split
  report/
    model.py              # immutable report view model
    latex.py              # Jinja2 rendering and escaping
    compiler.py           # offline Tectonic process wrapper
    templates/report.tex.j2
  ui/
    app.py
    main_window.py
    project_pages.py
    pair_models.py
    pair_editor.py
    calculation_review.py
    rules_manager.py
    report_page.py
packaging/
  insulation_coordination.spec
  tectonic-manifest.json
installer/insulation-coordination.iss
tests/
  fixtures/synthetic_rules.py
  domain/
  project/
  rules/
  calculation/
  report/
  ui/
  private/
```

---

### Task 1: Reproducible Python Package and Quality Gates

**Files:**
- Create: `pyproject.toml`
- Create: `src/insulation_coordination/__init__.py`
- Create: `src/insulation_coordination/cli.py`
- Create: `tests/test_package.py`
- Create: `.github/workflows/ci.yml`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `insulation_coordination.__version__: str`
- Produces: CLI entry point `icc = insulation_coordination.cli:main`

- [ ] **Step 1: Write the failing package smoke test**

```python
# tests/test_package.py
from insulation_coordination import __version__
from insulation_coordination.cli import main


def test_package_exposes_version(capsys):
    assert __version__ == "0.1.0"
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "0.1.0"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_package.py -v`
Expected: FAIL because the package does not exist.

- [ ] **Step 3: Add the package, pinned dependency ranges, and CLI**

```toml
# pyproject.toml
[project]
name = "insulation-coordination-calculator"
version = "0.1.0"
requires-python = ">=3.12,<3.14"
dependencies = [
  "jinja2>=3.1,<4",
  "pdfplumber>=0.11,<1",
  "platformdirs>=4,<5",
  "pydantic>=2.11,<3",
  "pypdf>=5,<7",
  "PySide6>=6.8,<7",
]

[project.scripts]
icc = "insulation_coordination.cli:main"

[dependency-groups]
dev = [
  "hypothesis>=6,<7",
  "mypy>=1.15,<2",
  "pyinstaller>=6,<7",
  "pytest>=8,<10",
  "pytest-cov>=6,<8",
  "pytest-qt>=4.4,<5",
  "ruff>=0.11,<1",
]

[build-system]
requires = ["hatchling>=1.27,<2"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/insulation_coordination"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--strict-markers"
markers = ["private_standard: requires ignored licensed PDFs"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.mypy]
python_version = "3.12"
strict = true
packages = ["insulation_coordination"]
```

```python
# src/insulation_coordination/__init__.py
__version__ = "0.1.0"
```

```python
# src/insulation_coordination/cli.py
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
```

- [ ] **Step 4: Lock dependencies and add Linux/Windows CI**

Run: `uv lock`
Create CI jobs that run `uv sync --locked --all-groups`, `ruff check .`, `mypy`, and `pytest` on `ubuntu-latest` and `windows-latest`, without private standards.

- [ ] **Step 5: Run all quality gates**

Run: `uv run ruff check . && uv run mypy && uv run pytest -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src tests .github .gitignore
git commit -m "build: establish Python application foundation"
```

---

### Task 2: Canonical Project, Net-Class, and Pair Domain Models

**Files:**
- Create: `src/insulation_coordination/domain/enums.py`
- Create: `src/insulation_coordination/domain/quantities.py`
- Create: `src/insulation_coordination/domain/project.py`
- Create: `src/insulation_coordination/project/pairs.py`
- Create: `src/insulation_coordination/project/resolver.py`
- Create: `tests/project/test_pairs.py`
- Create: `tests/project/test_resolver.py`

**Interfaces:**
- Produces: `canonical_pair_key(left: UUID, right: UUID) -> str`
- Produces: `reconcile_pairs(net_classes: tuple[NetClass, ...], existing: tuple[PairCase, ...]) -> tuple[PairCase, ...]`
- Produces: `resolve_effective_case(defaults, pair) -> EffectiveCase`

- [ ] **Step 1: Write failing tests for unordered pair generation and overrides**

```python
def test_three_net_classes_create_three_canonical_pairs():
    classes = tuple(NetClass(id=UUID(int=i), name=f"N{i}") for i in (1, 2, 3))
    pairs = reconcile_pairs(classes, ())
    assert [pair.key for pair in pairs] == [
        f"{UUID(int=1)}::{UUID(int=2)}",
        f"{UUID(int=1)}::{UUID(int=3)}",
        f"{UUID(int=2)}::{UUID(int=3)}",
    ]


def test_pair_frequency_and_impulse_override_project_defaults():
    effective = resolve_effective_case(
        ProjectDefaults(frequency_hz=Decimal("50000"), impulse_v=Decimal("4000")),
        PairCase(
            key="a::b",
            net_a=UUID(int=1),
            net_b=UUID(int=2),
            frequency_hz=OverrideValue.override(Decimal("100000")),
            impulse_v=OverrideValue.override(Decimal("6000")),
        ),
    )
    assert effective.frequency_hz.value == Decimal("100000")
    assert effective.frequency_hz.provenance is Provenance.PAIR_OVERRIDE
    assert effective.impulse_v.value == Decimal("6000")
```

- [ ] **Step 2: Run tests and confirm model/import failures**

Run: `uv run pytest tests/project/test_pairs.py tests/project/test_resolver.py -v`
Expected: FAIL because the domain models do not exist.

- [ ] **Step 3: Implement exact enums and Decimal-backed models**

Define `InsulationType(FUNCTIONAL, BASIC, REINFORCED)`, `Provenance`, `FieldCondition`, `ConstructionType`, and `Applicability`. Implement frozen Pydantic models for `NetClass`, `OverrideValue`, `ProjectDefaults`, `PairVoltages`, `PairCase`, and `EffectiveCase`. Reject equal net IDs and non-positive applicable voltage/frequency values.

```python
def canonical_pair_key(left: UUID, right: UUID) -> str:
    if left == right:
        raise ValueError("A pair requires two different net classes")
    first, second = sorted((str(left), str(right)))
    return f"{first}::{second}"
```

`reconcile_pairs` preserves existing cases by canonical key, creates missing combinations, removes orphaned pairs, and returns pairs in net-class display order.

- [ ] **Step 4: Implement default/override resolution with provenance**

Resolve every defaultable field into `EffectiveValue[T](value, provenance)`. Required pair voltages remain explicit pair inputs; blank and `NOT_APPLICABLE` remain distinct.

- [ ] **Step 5: Run focused and property tests**

Add a Hypothesis test proving pair count is `n*(n-1)//2`, keys are unique, and reversing IDs produces the same key.
Run: `uv run pytest tests/project -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/domain src/insulation_coordination/project tests/project
git commit -m "feat: model net classes and canonical insulation pairs"
```

---

### Task 3: Versioned `.icproj` Persistence and Atomic Saves

**Files:**
- Create: `src/insulation_coordination/project/persistence.py`
- Create: `tests/project/test_persistence.py`

**Interfaces:**
- Produces: `load_project(path: Path) -> Project`
- Produces: `save_project_atomic(path: Path, project: Project) -> None`
- Produces: `migrate_project_document(raw: dict[str, object]) -> dict[str, object]`

- [ ] **Step 1: Write failing round-trip and failure-safety tests**

```python
def test_project_round_trip_preserves_decimal_text(sample_project, tmp_path):
    path = tmp_path / "drive.icproj"
    save_project_atomic(path, sample_project)
    assert '"560.00"' in path.read_text(encoding="utf-8")
    assert load_project(path) == sample_project


def test_failed_replace_preserves_previous_file(sample_project, tmp_path, monkeypatch):
    path = tmp_path / "drive.icproj"
    path.write_text('{"schema_version":1,"sentinel":true}', encoding="utf-8")
    monkeypatch.setattr(os, "replace", Mock(side_effect=OSError("disk error")))
    with pytest.raises(ProjectSaveError, match="disk error"):
        save_project_atomic(path, sample_project)
    assert '"sentinel":true' in path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Verify failures**

Run: `uv run pytest tests/project/test_persistence.py -v`
Expected: FAIL because persistence functions are missing.

- [ ] **Step 3: Implement schema-versioned JSON serialization**

Serialize `Decimal` values as strings, UUIDs as strings, enums by stable value, and JSON with `sort_keys=True`, UTF-8, and a final newline. Reject unsupported future schema versions with `ProjectVersionError`.

- [ ] **Step 4: Implement same-directory atomic replacement**

Use `tempfile.NamedTemporaryFile(dir=path.parent, delete=False)`, flush and `os.fsync`, then `os.replace`. On any failure, remove only the known temporary file and retain the existing project.

- [ ] **Step 5: Test migrations and exact ruleset pinning**

Add fixtures for schema 1 and a future unsupported schema. Assert rule package ID/version/hash survive round trip and migration never overwrites the source.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/project/persistence.py tests/project/test_persistence.py
git commit -m "feat: add safe versioned project persistence"
```

---

### Task 4: Safe `.icrules` Schema, Archive, Validation, and Audit

**Files:**
- Create: `src/insulation_coordination/domain/rules.py`
- Create: `src/insulation_coordination/rules/archive.py`
- Create: `src/insulation_coordination/rules/validation.py`
- Create: `src/insulation_coordination/rules/audit.py`
- Create: `tests/rules/test_archive.py`
- Create: `tests/rules/test_audit.py`
- Create: `tests/fixtures/synthetic_rules.py`

**Interfaces:**
- Produces: `write_rule_package(path: Path, package: RulePackage) -> str`
- Produces: `load_rule_package(path: Path) -> RulePackage`
- Produces: `migrate_rule_package(package, target_schema) -> DraftRulePackage`
- Produces: `validate_rule_package(package) -> ValidationReport`
- Produces: `build_audit_inventory(package) -> AuditInventory`
- Produces: `export_table_csv(package: RulePackage, table_id: str, path: Path) -> None`
- Produces: `export_inventory_json(inventory: AuditInventory, path: Path) -> None`

- [ ] **Step 1: Write failing security and PDF-independent import tests**

```python
def test_approved_package_loads_without_source_pdfs(synthetic_package, tmp_path):
    path = tmp_path / "company.icrules"
    digest = write_rule_package(path, synthetic_package)
    loaded = load_rule_package(path)
    assert loaded.manifest.approved is True
    assert loaded.package_sha256 == digest


def test_unknown_formula_operator_is_rejected(package_dict):
    package_dict["formulas"][0]["expression"] = {"op": "python", "code": "open('x')"}
    with pytest.raises(RulePackageError, match="unknown operator"):
        RulePackage.model_validate(package_dict)
```

- [ ] **Step 2: Run tests and confirm failures**

Run: `uv run pytest tests/rules/test_archive.py tests/rules/test_audit.py -v`
Expected: FAIL because rule models/archive do not exist.

- [ ] **Step 3: Implement discriminated formula AST and table models**

Implement frozen Pydantic nodes for `Literal`, `Variable`, `Add`, `Multiply`, `Divide`, `Compare`, `Select`, `Minimum`, `Maximum`, `Round`, `Lookup`, and `LinearInterpolate`. Do not provide a generic expression string or `eval` path. Define `ParameterSet`, `SupportedRange`, table axes/cells with units, and `SourceReference(standard, edition, clause, table, figure, row, column, note)`.

- [ ] **Step 4: Implement deterministic ZIP and checksum validation**

Write canonical `manifest.json`, `tables.json`, `formulas.json`, and `mappings.json`, then `checksums.json` covering those four members. Normalize ZIP timestamps and member order. On load, reject missing/extra members, bad member hashes, draft approval state, unsupported schema/operator, and inconsistent package digest. A schema migration returns a new package identity in draft state and cannot be used until it is reviewed and approved again.

- [ ] **Step 5: Implement complete audit enumeration**

`build_audit_inventory` must count and expose every table cell, formula node, mapping, parameter set, supported range, source reference, checksum, and approval record. CSV export writes one row per table cell; inventory JSON records counts and validation results. Test exported counts equal the package contents, migration clears approval and changes identity, and neither archive nor audit export contains PDF bytes.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/domain/rules.py src/insulation_coordination/rules tests/rules tests/fixtures
git commit -m "feat: add safe private rules packages and auditing"
```

---

### Task 5: Decimal Formula Evaluation and Complete Trace Steps

**Files:**
- Create: `src/insulation_coordination/domain/trace.py`
- Create: `src/insulation_coordination/rules/evaluator.py`
- Create: `tests/rules/test_evaluator.py`

**Interfaces:**
- Produces: `evaluate_formula(formula, variables, tables) -> EvaluatedValue`
- `EvaluatedValue` contains `value: Decimal`, `unit: str`, `steps: tuple[TraceStep, ...]`

- [ ] **Step 1: Write failing formula, lookup, interpolation, and trace tests**

```python
def test_linear_interpolation_records_formula_values_and_cells(synthetic_table):
    result = evaluate_formula(
        LinearInterpolate(table_id="creepage", x=Variable(name="voltage")),
        {"voltage": Quantity(Decimal("150"), "V")},
        {"creepage": synthetic_table},
    )
    assert result.value == Decimal("1.50")
    assert result.steps[-1].symbolic == "y = y_0 + (x-x_0)(y_1-y_0)/(x_1-x_0)"
    assert "150 V" in result.steps[-1].substituted
    assert result.steps[-1].source_cells == ("100V", "200V")


def test_maximum_trace_identifies_governing_candidate():
    result = evaluate_formula(maximum_fixture(), {}, {})
    assert result.value == Decimal("5.5")
    assert result.steps[-1].reason == "impulse candidate governs"
```

- [ ] **Step 2: Run tests and verify failures**

Run: `uv run pytest tests/rules/test_evaluator.py -v`
Expected: FAIL because evaluator/trace types are missing.

- [ ] **Step 3: Implement recursive typed evaluation**

Use `Decimal` under `localcontext` with package-declared precision. Validate units at every operator. `Divide` rejects zero; `Lookup` rejects unsupported keys/ranges; `LinearInterpolate` records both bounding cells; `Round` applies only declared `ROUND_*` modes.

- [ ] **Step 4: Build report-ready trace data**

Every node returns a trace step with semantic rule ID, symbolic LaTeX, substituted expression with units, unrounded/rounded values, source reference, source cells, and reason. Child steps remain ordered before parent steps.

- [ ] **Step 5: Add property tests**

Use Hypothesis to prove interpolation returns endpoints exactly, maximum is not below any candidate, and archive round-tripping does not change evaluation.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/domain/trace.py src/insulation_coordination/rules/evaluator.py tests/rules/test_evaluator.py
git commit -m "feat: evaluate declarative rules with auditable traces"
```

---

### Task 6: IEC 60664-1 Functional, Basic, and Reinforced Engine

**Files:**
- Create: `src/insulation_coordination/calculation/engine.py`
- Create: `src/insulation_coordination/calculation/clearance.py`
- Create: `src/insulation_coordination/calculation/creepage.py`
- Create: `tests/calculation/test_part1.py`

**Interfaces:**
- Produces: `calculate_pair(effective: EffectiveCase, rules: RulePackage) -> PairResult`
- Produces internal: `calculate_clearance_candidates(effective: EffectiveCase, rules: RulePackage) -> tuple[DistanceCandidate, ...]`
- Produces internal: `calculate_creepage_candidates(effective: EffectiveCase, final_clearance_mm: Decimal, rules: RulePackage) -> tuple[DistanceCandidate, ...]`

- [ ] **Step 1: Write failing synthetic golden tests for all insulation types**

```python
@pytest.mark.parametrize(
    ("kind", "clearance", "creepage"),
    [
        (InsulationType.FUNCTIONAL, Decimal("2.0"), Decimal("3.0")),
        (InsulationType.BASIC, Decimal("3.0"), Decimal("4.0")),
        (InsulationType.REINFORCED, Decimal("5.5"), Decimal("8.0")),
    ],
)
def test_part1_paths_are_distinct(kind, clearance, creepage, case_factory, synthetic_rules):
    result = calculate_pair(case_factory(kind=kind, frequency_hz="30000"), synthetic_rules)
    assert result.clearance_mm == clearance
    assert result.creepage_mm == creepage
    assert result.trace.insulation_type is kind


def test_functional_path_does_not_apply_reinforced_scaling(case_factory, synthetic_rules):
    result = calculate_pair(
        case_factory(kind=InsulationType.FUNCTIONAL, frequency_hz="30000"),
        synthetic_rules,
    )
    assert "reinforced_scale" not in result.trace.semantic_rule_ids
```

- [ ] **Step 2: Run tests and verify failures**

Run: `uv run pytest tests/calculation/test_part1.py -v`
Expected: FAIL because calculation modules are missing.

- [ ] **Step 3: Implement clearance workflow selection**

Functional pairs select the approved Clause 5.2.4 semantic mapping and actual functional stresses. Basic/reinforced pairs select the Clause 5.2.5 mapping. Evaluate impulse and periodic candidates, field/pollution branches, insulation transformations, and maximum selection through the declarative evaluator.

- [ ] **Step 4: Implement creepage workflow and clearance floor**

Functional pairs select the Clause 5.3.4 mapping; basic/reinforced pairs select Clause 5.3.5. Evaluate RMS tracking, PCB/material, pollution, CTI, interpolation/rounding, and insulation transformation. Append an explicit `max(calculated_creepage, final_clearance)` trace step.

- [ ] **Step 5: Test blocking cases and invariants**

Cover blank versus justified not-applicable stress, unsupported special flags, out-of-range values, missing mappings, `reinforced >= basic`, and `creepage >= clearance`.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/calculation tests/calculation/test_part1.py
git commit -m "feat: calculate Part 1 insulation distances"
```

---

### Task 7: IEC 60664-4 High-Frequency Paths, Field Iteration, and Altitude

**Files:**
- Create: `src/insulation_coordination/calculation/high_frequency.py`
- Create: `tests/calculation/test_high_frequency.py`

**Interfaces:**
- Produces: `calculate_high_frequency_candidates(effective, base, rules) -> HfCandidates`
- Produces: `iterate_field_clearance(effective: EffectiveCase, base: DistanceCandidate, rules: RulePackage) -> IterationResult`

- [ ] **Step 1: Write failing boundary and applicability tests**

```python
def test_part4_starts_only_above_30_khz(case_factory, synthetic_rules):
    at_boundary = calculate_pair(case_factory(frequency_hz="30000"), synthetic_rules)
    above = calculate_pair(case_factory(frequency_hz="30000.1"), synthetic_rules)
    assert at_boundary.trace.used_part4 is False
    assert above.trace.used_part4 is True


def test_functional_hf_requires_approved_mapping(case_factory, rules_without_functional_hf):
    result = calculate_pair(
        case_factory(kind=InsulationType.FUNCTIONAL, frequency_hz="100000"),
        rules_without_functional_hf,
    )
    assert result.status is CalculationStatus.BLOCKED
    assert result.errors[0].code == "FUNCTIONAL_HF_MAPPING_MISSING"
```

- [ ] **Step 2: Verify failures**

Run: `uv run pytest tests/calculation/test_high_frequency.py -v`
Expected: FAIL because high-frequency paths are absent.

- [ ] **Step 3: Implement Part 4 candidate routing**

Use the approved mapping for periodic peak/frequency candidates. Route inhomogeneous directly; route homogeneous/approximately homogeneous through the declared critical-frequency formula and bounded iteration. Require an explicit functional applicability mapping.

- [ ] **Step 4: Implement bounded geometry iteration**

Start from the declared base clearance, evaluate radius criterion and critical-frequency branch, recompute until the package-declared tolerance is met, and stop at the declared maximum iteration count. Record every iteration. Return blocking `HF_ITERATION_DID_NOT_CONVERGE` if no convergence.

- [ ] **Step 5: Apply altitude after governing clearance and rerun creepage floor**

Evaluate altitude correction only after all clearance candidates are selected, then apply the final corrected clearance as the creepage floor. Test 2 000 m boundary, interpolation, monotonicity, and unsupported altitude.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/calculation/high_frequency.py tests/calculation/test_high_frequency.py
git commit -m "feat: add high-frequency and altitude calculations"
```

---

### Task 8: Deterministic Calculation Grouping and Safe Manual Splits

**Files:**
- Create: `src/insulation_coordination/calculation/grouping.py`
- Create: `tests/calculation/test_grouping.py`

**Interfaces:**
- Produces: `calculation_signature(result: PairResult) -> str`
- Produces: `group_results(results: tuple[PairResult, ...], splits: tuple[GroupSplit, ...]) -> tuple[CalculationGroup, ...]`
- Produces: `split_group(groups: tuple[CalculationGroup, ...], group_id: str, pair_ids: tuple[str, ...]) -> tuple[CalculationGroup, ...]`
- Produces: `merge_groups(groups: tuple[CalculationGroup, ...], pair_ids: tuple[str, ...]) -> tuple[CalculationGroup, ...]`

- [ ] **Step 1: Write failing grouping tests**

```python
def test_identical_results_group_and_different_inputs_do_not(result_factory):
    a = result_factory(pair_id="IC-01")
    b = result_factory(pair_id="IC-02")
    c = result_factory(pair_id="IC-03", rms_v="501")
    groups = group_results((a, b, c), ())
    assert [group.pair_ids for group in groups] == [("IC-01", "IC-02"), ("IC-03",)]


def test_manual_split_never_merges_different_signatures(result_factory):
    groups = group_results(
        (result_factory(pair_id="A"), result_factory(pair_id="B", rms_v="501")),
        (),
    )
    with pytest.raises(GroupingError, match="different calculation signatures"):
        merge_groups(groups, ("A", "B"))
```

- [ ] **Step 2: Verify failures**

Run: `uv run pytest tests/calculation/test_grouping.py -v`
Expected: FAIL because grouping is missing.

- [ ] **Step 3: Implement canonical signature**

Hash canonical JSON containing rules-package hash, engine calculation version, effective input values/applicability, semantic branch IDs, candidates, corrections, rounding, final values, warnings, and verification requirements. Exclude pair ID and presentation split metadata.

- [ ] **Step 4: Implement grouping and split persistence**

Sort groups by first pair display order. Allow a saved split only within one automatic signature; reject merge across signatures. Recalculate groups whenever results change.

- [ ] **Step 5: Commit**

```bash
git add src/insulation_coordination/calculation/grouping.py tests/calculation/test_grouping.py
git commit -m "feat: group identical calculations safely"
```

---

### Task 9: Immutable Report Model, LaTeX Formulas, and PDF Compilation

**Files:**
- Create: `src/insulation_coordination/report/model.py`
- Create: `src/insulation_coordination/report/latex.py`
- Create: `src/insulation_coordination/report/compiler.py`
- Create: `src/insulation_coordination/report/templates/report.tex.j2`
- Create: `tests/report/test_latex.py`
- Create: `tests/report/test_compiler.py`

**Interfaces:**
- Produces: `build_report_model(project, results, groups, rules) -> ReportModel`
- Produces: `render_latex(model: ReportModel) -> str`
- Produces: `compile_pdf(tex_path, output_path, tectonic) -> CompileResult`

- [ ] **Step 1: Write failing formula/reference report test**

```python
def test_report_renders_symbolic_and_substituted_formula(report_model):
    tex = render_latex(report_model)
    assert r"y = y_0 + \frac{(x-x_0)(y_1-y_0)}{x_1-x_0}" in tex
    assert r"150\,\mathrm{V}" in tex
    assert "IEC 60664-1:2020, 5.3.4, Table F.5" in tex
    assert "entire synthetic table" not in tex
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/report/test_latex.py -v`
Expected: FAIL because reporting modules are absent.

- [ ] **Step 3: Build immutable report model**

Reject any blocked pair. Snapshot project/rules/engine metadata, effective inputs, matrix rows, groups, candidates, trace steps, formulas, substituted values, lookup cells, references, warnings, and approval metadata into frozen models.

- [ ] **Step 4: Render the complete LaTeX document**

Implement escaping for user text separately from trusted formula LaTeX. Template sections: cover/control, basis/defaults, net classes, landscape repeated-header matrix, grouped calculations, warnings, provenance. Never render complete rules tables.

- [ ] **Step 5: Wrap pinned offline Tectonic safely**

Use `subprocess.run([str(tectonic), "--offline", "--outdir", str(output_path.parent), str(tex_path)], shell=False, timeout=120)`. Return stdout/stderr in `CompileResult`; retain `.tex` and log on failure. Test with a fake executable and add an optional integration test skipped when Tectonic is unavailable.

- [ ] **Step 6: Render and inspect a synthetic PDF**

Compile the synthetic report, use pypdf to verify pages/text/headings, and manually inspect rendered pages for landscape tables, clipping, headers, and group page breaks.

- [ ] **Step 7: Commit**

```bash
git add src/insulation_coordination/report tests/report
git commit -m "feat: generate auditable LaTeX and PDF reports"
```

---

### Task 10: Recognized IEC PDF Importer and Approval Workflow

**Files:**
- Create: `src/insulation_coordination/rules/importer/identify.py`
- Create: `src/insulation_coordination/rules/importer/extract.py`
- Create: `src/insulation_coordination/rules/importer/approval.py`
- Create: `src/insulation_coordination/rules/importer/recipes/iec60664_1_2020.py`
- Create: `src/insulation_coordination/rules/importer/recipes/iec60664_4_2005.py`
- Create: `tests/rules/test_importer.py`
- Create: `tests/private/test_supplied_standards.py`

**Interfaces:**
- Produces: `identify_standard(path: Path) -> StandardIdentity`
- Produces: `extract_draft(paths: tuple[Path, ...]) -> DraftRulePackage`
- Produces: `approve_draft(draft, approver, notes) -> RulePackage`

- [ ] **Step 1: Write failing recognized/unknown-document tests using synthetic PDFs**

```python
def test_identifies_supported_synthetic_document(synthetic_part1_pdf):
    identity = identify_standard(synthetic_part1_pdf)
    assert identity.standard == "IEC 60664-1"
    assert identity.edition == "2020"
    assert len(identity.sha256) == 64


def test_unknown_document_is_rejected(tmp_path):
    path = tmp_path / "unknown.pdf"
    create_pdf(path, text="Unrelated document")
    with pytest.raises(UnsupportedStandardError):
        identify_standard(path)
```

- [ ] **Step 2: Verify failures**

Run: `uv run pytest tests/rules/test_importer.py -v`
Expected: FAIL because importer modules are absent.

- [ ] **Step 3: Implement identification and extraction recipes**

Use metadata plus multiple independent text anchors; record the full SHA-256. Recipes declare semantic table/formula IDs, page/table anchors, expected dimensions, units, references, and consistency assertions, but no extracted IEC values. Reject ambiguous/missing anchors.

- [ ] **Step 4: Implement draft corrections and approval**

Drafts remain unusable. Record every automatic extraction and manual correction in an approval log. `approve_draft` requires all extraction checks, table audits, formula audits, and the explicit Part 1/Part 4 compatibility mapping to pass.

- [ ] **Step 5: Add ignored private integration tests**

`tests/private/test_supplied_standards.py` locates the two ignored filenames under `standards/`, skips with a clear message if absent, extracts a draft, checks expected semantic IDs/dimensions/references, and requires a separately reviewed local golden digest file under ignored `private-rules/`. Do not print table contents in test output.

- [ ] **Step 6: Commit public importer code only**

```bash
git add src/insulation_coordination/rules/importer tests/rules/test_importer.py tests/private/test_supplied_standards.py
git commit -m "feat: import recognized standards into draft rules"
```

---

### Task 11: Desktop Shell, Project Setup, and Net-Class Editing

**Files:**
- Create: `src/insulation_coordination/ui/app.py`
- Create: `src/insulation_coordination/ui/main_window.py`
- Create: `src/insulation_coordination/ui/project_pages.py`
- Modify: `src/insulation_coordination/cli.py`
- Create: `tests/ui/test_project_pages.py`

**Interfaces:**
- Produces: `create_application(argv) -> QApplication`
- Produces: `MainWindow.open_project(path)` and `MainWindow.save_project(path)`
- Produces signals: `project_changed(Project)` and `validation_changed(ValidationReport)`

- [ ] **Step 1: Write failing pytest-qt workflow test**

```python
def test_adding_three_net_classes_creates_three_pairs(qtbot, project_page):
    qtbot.addWidget(project_page)
    project_page.add_net_class("HV+")
    project_page.add_net_class("HV-")
    project_page.add_net_class("PE")
    assert project_page.project.net_class_names == ("HV+", "HV-", "PE")
    assert len(project_page.project.pairs) == 3
```

- [ ] **Step 2: Verify failure**

Run: `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_project_pages.py -v`
Expected: FAIL because UI modules are missing.

- [ ] **Step 3: Build navigation shell and project pages**

Create the five approved pages: Project defaults, Net classes, Pair matrix, Calculation review, Report. Add an independent Rules Manager menu action. Bind widgets to immutable project updates through application services; no calculation logic in widgets.

- [ ] **Step 4: Add new/open/save and dirty-state behavior**

Use native file dialogs for `.icproj`. Confirm before closing/replacing a dirty project. Display required rules-package ID/hash and block calculation UI when unavailable.

- [ ] **Step 5: Test rename/delete and atomic-save errors**

Assert net rename preserves stable IDs/pairs; delete asks confirmation and removes orphaned pairs; save failure shows actionable error and leaves dirty state.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/ui src/insulation_coordination/cli.py tests/ui/test_project_pages.py
git commit -m "feat: add desktop project and net-class workflow"
```

---

### Task 12: Coverage Matrix, Pair List, Detailed Editor, and Review

**Files:**
- Create: `src/insulation_coordination/ui/pair_models.py`
- Create: `src/insulation_coordination/ui/pair_editor.py`
- Create: `src/insulation_coordination/ui/calculation_review.py`
- Create: `tests/ui/test_pair_workflow.py`

**Interfaces:**
- Produces: `CoverageMatrixModel`, `PairListModel`, `PairEditor`, `CalculationReviewPage`
- Consumes: `resolve_effective_case`, `calculate_pair`, `group_results`

- [ ] **Step 1: Write failing matrix symmetry and override tests**

```python
def test_matrix_lower_half_references_same_pair(qtbot, pair_page):
    qtbot.addWidget(pair_page)
    upper = pair_page.matrix_model.pair_at(0, 1)
    lower = pair_page.matrix_model.pair_at(1, 0)
    assert upper is lower


def test_frequency_override_is_visible_and_recalculates(qtbot, pair_page):
    pair_page.select_pair("IC-02")
    pair_page.editor.set_frequency_override("100 kHz")
    assert pair_page.editor.frequency_source_text == "Override"
    assert pair_page.project.pair("IC-02").frequency_hz.value == Decimal("100000")
    assert pair_page.result("IC-02").trace.used_part4 is True
```

- [ ] **Step 2: Verify failure**

Run: `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_pair_workflow.py -v`
Expected: FAIL because pair UI is missing.

- [ ] **Step 3: Implement square coverage and flat pair models**

Matrix diagonal is non-editable; lower cells mirror the same pair object; upper cells show complete/warning/blocked state. Pair list exposes input/result columns and supports sorting without changing project order.

- [ ] **Step 4: Implement detailed editor**

Provide manual RMS, steady peak, recurring peak, temporary peak, impulse, frequency, insulation type, field/geometry, altitude, pollution, construction, CTI, and special-condition fields. Every defaultable field has Default/Override control; voltage applicability requires value or justified N/A.

- [ ] **Step 5: Implement calculation review and grouping**

Show candidates, formulas, substitutions, references, warnings, errors, and group membership. Recalculate immediately after valid changes; clear stale results after invalid changes. Allow split only; reject cross-signature merge.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/ui/pair_models.py src/insulation_coordination/ui/pair_editor.py src/insulation_coordination/ui/calculation_review.py tests/ui/test_pair_workflow.py
git commit -m "feat: add pair matrix editing and calculation review"
```

---

### Task 13: Rules Manager, PDF Review, and Full Package Audit UI

**Files:**
- Create: `src/insulation_coordination/ui/rules_manager.py`
- Create: `tests/ui/test_rules_manager.py`

**Interfaces:**
- Produces: `RulesManagerWindow`
- Consumes: archive, audit, importer, and approval interfaces from Tasks 4 and 10

- [ ] **Step 1: Write failing no-PDF import and full-audit tests**

```python
def test_imported_package_is_usable_without_pdfs(qtbot, rules_manager, approved_icrules):
    qtbot.addWidget(rules_manager)
    rules_manager.import_package(approved_icrules)
    assert rules_manager.active_package.approved is True
    assert rules_manager.pdf_required is False


def test_audit_tree_enumerates_every_table_cell_and_formula(rules_manager, synthetic_package):
    rules_manager.set_package(synthetic_package)
    assert rules_manager.audit_cell_count == synthetic_package.total_cell_count
    assert rules_manager.audit_formula_count == len(synthetic_package.formulas)
```

- [ ] **Step 2: Verify failure**

Run: `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_rules_manager.py -v`
Expected: FAIL because Rules Manager is missing.

- [ ] **Step 3: Implement approved `.icrules` import**

Use a native file dialog, validate schema/checksums/approval/compatibility, copy the exact package into `platformdirs.user_data_path()/rules`, and show identity/hash. Never ask for PDFs on this path.

- [ ] **Step 4: Implement complete audit browser**

Tree sections: Manifest, Checksums, Tables, Formulas, Mappings, Validation. Table views expose all rows/columns/cells/units/references. Formula view shows AST and rendered math. Add semantic-ID/reference search plus private CSV/inventory export into a user-selected directory.

- [ ] **Step 5: Implement PDF extraction review**

For the maintainer path, show source page through QtPdf beside extracted draft values, extraction checks, manual corrections, compatibility mapping, and approval form. Disable Export Approved Package until every check/audit is accepted.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/ui/rules_manager.py tests/ui/test_rules_manager.py
git commit -m "feat: add private rules import review and audit UI"
```

---

### Task 14: Report Page and End-to-End Desktop Workflow

**Files:**
- Create: `src/insulation_coordination/ui/report_page.py`
- Create: `tests/ui/test_report_page.py`
- Create: `tests/test_end_to_end.py`

**Interfaces:**
- Produces: `ReportPage.generate(destination: Path) -> CompileResult`
- Consumes: report/grouping/project/rules interfaces

- [ ] **Step 1: Write failing blocked/final report tests**

```python
def test_report_is_blocked_when_any_pair_is_incomplete(report_page):
    assert report_page.generate_enabled is False
    assert "IC-03: long-term RMS is missing" in report_page.blocking_summary


def test_complete_project_generates_tex_and_pdf(complete_workspace, tmp_path):
    result = complete_workspace.report_page.generate(tmp_path)
    assert result.tex_path.exists()
    assert result.pdf_path.exists()
    assert "IEC 60664-1:2020" in result.tex_path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Verify failure**

Run: `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_report_page.py -v`
Expected: FAIL because report page is absent.

- [ ] **Step 3: Implement group controls, preview, and export**

Show automatic groups and allowed splits, document metadata, output basename/directory, validation summary, and generated artifact links. Generate only after recalculating all pairs against the exact installed rules hash.

- [ ] **Step 4: Add synthetic end-to-end test**

Create project -> add four nets -> fill six pairs covering functional/basic/reinforced and Part 4 -> save/reload -> calculate -> group -> render `.tex` -> compile with fake/pinned Tectonic -> assert matrix rows, formulas, references, and artifact paths.

- [ ] **Step 5: Commit**

```bash
git add src/insulation_coordination/ui/report_page.py tests/ui/test_report_page.py tests/test_end_to_end.py
git commit -m "feat: complete desktop report workflow"
```

---

### Task 15: Windows Packaging, Offline Compiler Bundle, and Release Acceptance

**Files:**
- Create: `packaging/insulation_coordination.spec`
- Create: `packaging/tectonic-manifest.json`
- Create: `installer/insulation-coordination.iss`
- Create: `.github/workflows/windows-package.yml`
- Create: `docs/release-checklist.md`
- Create: `README.md`

**Interfaces:**
- Produces: signed-or-unsigned versioned Windows installer artifact
- Produces: installed `icc.exe` with `.icproj`/`.icrules` file associations

- [ ] **Step 1: Write failing packaged smoke script**

Add a Windows CI script that installs into a clean temporary directory, runs `icc.exe --version`, opens a synthetic `.icproj`, imports a synthetic `.icrules` without PDFs, generates `.tex`/PDF offline, and asserts no network access is required.

- [ ] **Step 2: Build PyInstaller application**

Include Qt plugins (Widgets, Pdf), Jinja templates, schemas, application icons, and the pinned Tectonic executable/resource bundle. Exclude `standards/`, `private-rules/`, `.icrules`, `.icproj`, audits, and private tests. Store Tectonic version, licence, bundle hash, and executable hash in `tectonic-manifest.json`; verify hashes at application startup.

- [ ] **Step 3: Build Inno Setup installer**

Install per-user by default, create Start Menu entry, associate `.icproj` with open and `.icrules` with import, and support clean uninstall without deleting user projects or installed private rules.

- [ ] **Step 4: Run release acceptance matrix**

On a clean Windows VM verify:

1. no Python/LaTeX preinstalled;
2. approved `.icrules` imports without PDFs;
3. all rules tables/formulas are auditable;
4. functional/basic/reinforced plus >30 kHz cases calculate;
5. save/reopen reproduces results with exact hashes;
6. incomplete pair blocks final report;
7. `.tex` and PDF contain formulas/substitutions/references;
8. generated PDF has no clipping or broken landscape tables;
9. public source/archive contains no private standards or derived rule data.

- [ ] **Step 5: Run full repository verification**

Run: `uv run ruff check . && uv run mypy && uv run pytest -v`
Run Windows package workflow and retain installer, test log, and synthetic report as CI artifacts.
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add packaging installer .github/workflows/windows-package.yml docs/release-checklist.md README.md
git commit -m "build: package and verify offline Windows release"
```
