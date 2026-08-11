# Figure 7 AC basis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Figure 7's unsourced `voltage_basis="ac_peak"` with a new `ac_unspecified` token, so the approved-package contract states only what IEC 62477-1:2022 states and a consumer presenting an RMS or peak quantity cannot obtain that curve.

**Architecture:** One token added to `FaultTimeVoltageSelector.voltage_basis`, one selector changed in the Figure 7 curve recipe. Everything downstream follows without further edits: `dvc.fault_applicability` derives its vocabulary from the curve recipes, and `select_curve_variant` compares whole selectors for equality, so the refusal is structural rather than coded. Remaining work is updating the tests that pin the old basis and adding two guards.

**Tech Stack:** Python 3.13, Pydantic 2 frozen models, pytest, ruff, mypy strict, `uv`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-11-issue-50-figure-7-basis-design.md`. Read it before Task 1.
- The **only** justification permitted in this repository, its tests, its commit messages, the issue or the PR: *"Figure 7 identifies the variant as AC without specifying RMS or peak. Therefore the semantic contract uses `ac_unspecified` and consumers must not infer a more specific basis."* Nothing else about the maintainer's review evidence — not numbers, not numberless comparisons with any other table or figure.
- No licensed IEC value, table heading, note or clause wording in any committed file. This repository is public.
- `ac_rms` stays in the vocabulary. It is part of the public model contract and has seven usages across `src` and `tests`; removing it is an unrelated contract change.
- Figures 5 and 6 do not change.
- Maintenance rule, recorded in the model docstring: nobody may narrow `ac_unspecified` to `ac_rms` or `ac_peak` without new explicit normative evidence stating the more specific basis.
- Consumer rule, carried to #53/#36/#37, not implemented here: `ac_unspecified` is a source-contract identity, never a wildcard, and a consumer must not coerce a known RMS or peak quantity to it.
- `uv` is not on PATH. Every command below must be run as written, including the PATH prefix. PowerShell:
  ```
  $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
  ```
- Qt tests need `$env:QT_QPA_PLATFORM = "offscreen"`. No task here touches Qt, but the full-suite run in Task 4 does.
- The private licensed-document tests skip on this machine (no `standards/` directory). Do not attempt to make them run.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `src/insulation_coordination/domain/rules.py` | `FaultTimeVoltageSelector.voltage_basis` vocabulary and the meaning of `ac_unspecified` | 1 |
| `tests/rules/test_piecewise_curves.py` | Vocabulary test; curve model and selection behaviour | 1 |
| `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/curves.py` | Figure 7's declared variant slots | 2 |
| `tests/rules/importer/iec62477_2022/test_curve_recipe.py` | Per-figure slot inventory, asserted independently of the recipe | 2, 3 |
| `tests/rules/importer/iec62477_2022/test_figure_curve_proposals.py` | Selector probes against the projected curve rule; basis-mismatch refusal | 2, 3 |
| `tests/rules/importer/iec62477_2022/test_dvc_clause_projection.py` | `dvc.fault_applicability` routes | 2 |

No file is created. No file needs splitting.

---

### Task 1: Add the `ac_unspecified` basis token

**Files:**
- Modify: `src/insulation_coordination/domain/rules.py:429-433`
- Test: `tests/rules/test_piecewise_curves.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `FaultTimeVoltageSelector.voltage_basis` accepts the string literal `"ac_unspecified"` in addition to `"ac_rms"`, `"ac_peak"`, `"dc"`. Tasks 2 and 3 construct selectors with it.

- [ ] **Step 1: Write the failing test**

Append to `tests/rules/test_piecewise_curves.py`. `get_args`, `FaultTimeVoltageSelector` and `pytest` are already imported at the top of that file.

```python
def test_voltage_basis_vocabulary_carries_an_unspecified_ac_token() -> None:
    """Figure 7 identifies its variant as AC without specifying RMS or peak.

    The token exists so that contract can be stated exactly, instead of a specific basis
    being asserted on the source's behalf.
    """
    permitted = get_args(FaultTimeVoltageSelector.model_fields["voltage_basis"].annotation)
    assert set(permitted) == {"ac_rms", "ac_peak", "ac_unspecified", "dc"}


def test_a_selector_can_carry_the_unspecified_ac_basis() -> None:
    selector = FaultTimeVoltageSelector(
        subject="conductive_accessible_part",
        voltage_basis="ac_unspecified",
        dvc_context=None,
        environment_context=None,
    )
    assert selector.voltage_basis == "ac_unspecified"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/test_piecewise_curves.py -k unspecified -v
```

Expected: both FAIL. The vocabulary test fails on the set comparison; the constructor test fails with a Pydantic `ValidationError` reporting that `ac_unspecified` is not a permitted literal.

- [ ] **Step 3: Add the token and record what it means**

In `src/insulation_coordination/domain/rules.py`, replace the whole `FaultTimeVoltageSelector` class:

```python
class FaultTimeVoltageSelector(FrozenModel):
    """Which curve variant a fault-time voltage question is asking about.

    ``voltage_basis`` names the quantity the source draws its curve against.
    ``ac_unspecified`` means the source identifies the variant as AC without specifying
    RMS or peak: it is a source-contract identity, never a wildcard. A consumer whose own
    engineering quantity is RMS or peak submits ``ac_rms`` or ``ac_peak`` and must not
    coerce that input to ``ac_unspecified`` in order to obtain a curve.

    Nobody may narrow ``ac_unspecified`` to a more specific basis without new explicit
    normative evidence stating that basis for the figure in question.
    """

    subject: TypingLiteral["accessible_circuit", "conductive_accessible_part"]
    voltage_basis: TypingLiteral["ac_rms", "ac_peak", "ac_unspecified", "dc"]
    dvc_context: Identifier | None
    environment_context: Identifier | None
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/test_piecewise_curves.py -v
```

Expected: PASS, whole file, no failures. The rest of the file constructs `dc` selectors and is unaffected.

- [ ] **Step 5: Check the type gate**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run mypy
```

Expected: `Success: no issues found`. Widening a `Literal` cannot break an existing assignment, so no call site should need a change; if mypy reports one, that call site was narrowing the basis and belongs in Task 2's discussion, not silenced.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/domain/rules.py tests/rules/test_piecewise_curves.py
git commit -m "feat(rules): add an unspecified AC basis to the curve selector vocabulary

A figure may identify a curve as AC without stating whether the quantity is
RMS or peak. Until now the vocabulary offered only the two specific bases, so
a recipe describing such a figure had to assert one of them on the source's
behalf.

ac_unspecified is a source-contract identity, not a wildcard, and the model
records the rule that nobody may narrow it without new explicit normative
evidence.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Figure 7's AC variant declares `ac_unspecified`

**Files:**
- Modify: `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/curves.py:61-66`
- Modify: `tests/rules/importer/iec62477_2022/test_curve_recipe.py:42-45`
- Modify: `tests/rules/importer/iec62477_2022/test_figure_curve_proposals.py:191-195` and `:210-215`
- Modify: `tests/rules/importer/iec62477_2022/test_dvc_clause_projection.py:135-147`

**Interfaces:**
- Consumes: `voltage_basis="ac_unspecified"` from Task 1.
- Produces: `CURVES[2].variant_slots == (dc slot, ac_unspecified slot)` for `conductive_accessible_part`; `dvc.fault_applicability`'s `voltage_basis` input allows `("dc", "ac_peak", "ac_unspecified")` and its fourth row matches `(conductive_accessible_part, ac_unspecified)`. Task 3's guards read both.

- [ ] **Step 1: Write the failing tests**

Three edits, all pinning the new contract before it exists.

In `tests/rules/importer/iec62477_2022/test_curve_recipe.py`, inside `test_curve_specs_declare_the_exact_eight_semantic_roles`, replace the Figure 7 basis tuple:

```python
    assert tuple(selector.voltage_basis for selector in selectors[2]) == (
        "dc",
        "ac_unspecified",
    )
```

In `tests/rules/importer/iec62477_2022/test_figure_curve_proposals.py`, in `test_none_dimensions_do_not_wildcard`, the probe keeps the *correct* basis and varies only the context — that test exists to prove a wrong `dvc_context` defeats a match, and a probe wrong on two dimensions at once would no longer isolate the context:

```python
    # A selector with a DVC context must NOT match the variant whose context is None.
    probe = FaultTimeVoltageSelector(
        subject="conductive_accessible_part",
        voltage_basis="ac_unspecified",
        dvc_context="dvc-a",
        environment_context=None,
    )
```

In the same file, in `test_exact_selector_evaluates_matching_variant`:

```python
        FaultTimeVoltageSelector(
            subject="conductive_accessible_part",
            voltage_basis="ac_unspecified",
            dvc_context=None,
            environment_context=None,
        ),
```

In `tests/rules/importer/iec62477_2022/test_dvc_clause_projection.py`, in `test_projection_evaluates_all_four_curve_selector_routes`:

```python
    for subject, basis in (
        ("accessible_circuit", "dc"),
        ("accessible_circuit", "ac_peak"),
        ("conductive_accessible_part", "dc"),
        ("conductive_accessible_part", "ac_unspecified"),
    ):
```

- [ ] **Step 2: Run them to verify they fail**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/iec62477_2022/test_curve_recipe.py tests/rules/importer/iec62477_2022/test_figure_curve_proposals.py tests/rules/importer/iec62477_2022/test_dvc_clause_projection.py -v
```

Expected: FAIL. `test_curve_specs_declare_the_exact_eight_semantic_roles` fails on the tuple comparison, `test_exact_selector_evaluates_matching_variant` fails because the projected rule still holds an `ac_peak` variant so the probe returns `no_match`, and the clause-projection route test fails because `evaluate_decision` gets a `voltage_basis` outside the rule's allowed values.

`test_none_dimensions_do_not_wildcard` **passes throughout** — it asserts no match, and it gets no match either way. That is expected, not a sign the edit was pointless: the edit restores its ability to isolate the context dimension once the basis is correct.

- [ ] **Step 3: Change the declared slot**

In `src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/curves.py`, the second slot of `"7"`:

```python
    "7": (
        FaultTimeVoltageSelector(
            subject="conductive_accessible_part",
            voltage_basis="dc",
            dvc_context=None,
            environment_context=None,
        ),
        # Figure 7 identifies the variant as AC without specifying RMS or peak. Therefore
        # the semantic contract uses ac_unspecified and consumers must not infer a more
        # specific basis.
        FaultTimeVoltageSelector(
            subject="conductive_accessible_part",
            voltage_basis="ac_unspecified",
            dvc_context=None,
            environment_context=None,
        ),
    ),
```

Nothing else in `src/` changes. Do not edit `clauses.py`: it derives the fault-applicability vocabulary from `CURVES`, which is the whole reason that rule follows for free.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/iec62477_2022/ -v
```

Expected: PASS, whole directory. If `test_projected_variants_have_exact_distinct_selectors` or the aggregate-hash tests fail, the cause is a hand-written selector somewhere else in that file that still says `ac_peak` for `conductive_accessible_part`; the `_variants` helper derives from `CURVES` and needs no edit.

- [ ] **Step 5: Run the whole non-Qt suite for fallout**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules tests/domain -q
```

Expected: PASS. `tests/ui/test_curve_review.py` builds its own synthetic `ac_rms` curve and does not read the real Figure 7, so it is unaffected; it runs in Task 4 anyway.

- [ ] **Step 6: Commit**

```bash
git add src/insulation_coordination/rules/importer/recipes/iec62477_1_2022/curves.py tests/rules/importer/iec62477_2022/
git commit -m "fix(rules): stop asserting a peak basis for Figure 7 (#50)

Figure 7 identifies the variant as AC without specifying RMS or peak.
Therefore the semantic contract uses ac_unspecified and consumers must not
infer a more specific basis.

The fault-applicability rule follows without an edit, because it derives its
subject and basis vocabulary from the curve recipes rather than declaring its
own. Selection is exact, so a consumer probing with ac_rms or ac_peak now
gets no match instead of a curve drawn against a basis nobody stated.

This changes the canonical hash of the aggregate dvc.fault_time_voltage rule,
so a rebuilt package carries a new semantic proposal and digest and needs
renewed review. Already-reviewed curve geometry does not need re-digitizing,
and an existing approved package still loads because ac_peak remains a valid
token.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Two guards — slot inventory and basis-mismatch refusal

**Files:**
- Modify: `tests/rules/importer/iec62477_2022/test_curve_recipe.py:32-51`
- Modify: `tests/rules/importer/iec62477_2022/test_figure_curve_proposals.py` (append after `test_none_dimensions_do_not_wildcard`)

**Interfaces:**
- Consumes: `CURVES` from Task 2 and the vocabulary from Task 1.
- Produces: nothing further tasks depend on.

- [ ] **Step 1: Replace the roles test with a per-figure inventory guard**

In `tests/rules/importer/iec62477_2022/test_curve_recipe.py`, add two imports at the top:

```python
from typing import get_args

from insulation_coordination.domain.rules import FaultTimeVoltageSelector
```

Then replace the whole of `test_curve_specs_declare_the_exact_eight_semantic_roles` with an independently stated inventory. Restating the slots here is deliberate: the recipe and the guard must be able to disagree, or an edit to one figure could silently redefine another.

```python
#: The reviewed slot inventory, stated independently of the recipe so the two can
#: disagree: (subject, voltage_basis, dvc_context, environment_context) per figure.
_EXPECTED_SLOTS: dict[str, tuple[tuple[str, str, str | None, str | None], ...]] = {
    "5": (
        ("accessible_circuit", "dc", "b", "dry"),
        ("accessible_circuit", "dc", "as", "dry"),
        ("accessible_circuit", "dc", "as", "wet_and_saltwater_wet"),
    ),
    "6": (
        ("accessible_circuit", "ac_peak", "b", "dry"),
        ("accessible_circuit", "ac_peak", "as", "dry"),
        ("accessible_circuit", "ac_peak", "as", "wet_and_saltwater_wet"),
    ),
    # Figure 7 identifies the variant as AC without specifying RMS or peak. Therefore the
    # semantic contract uses ac_unspecified and consumers must not infer a more specific
    # basis.
    "7": (
        ("conductive_accessible_part", "dc", None, None),
        ("conductive_accessible_part", "ac_unspecified", None, None),
    ),
}


def test_each_figure_declares_its_exact_slot_inventory() -> None:
    declared = {
        spec.figure: tuple(
            (
                selector.subject,
                selector.voltage_basis,
                selector.dvc_context,
                selector.environment_context,
            )
            for selector in spec.variant_slots
        )
        for spec in CURVES
    }
    assert declared == _EXPECTED_SLOTS


def test_every_declared_basis_belongs_to_the_model_vocabulary() -> None:
    """A recipe cannot invent a basis token the contract does not define."""
    permitted = set(get_args(FaultTimeVoltageSelector.model_fields["voltage_basis"].annotation))
    declared = {selector.voltage_basis for spec in CURVES for selector in spec.variant_slots}
    assert declared <= permitted
```

- [ ] **Step 2: Run them to verify they pass**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/iec62477_2022/test_curve_recipe.py -v
```

Expected: PASS. These guards describe the contract Task 2 just established, so they pass immediately — they are regression guards, not red-green steps. To prove the inventory guard bites, temporarily change one entry of `_EXPECTED_SLOTS` to `"ac_peak"`, re-run, see it fail, then change it back.

- [ ] **Step 3: Write the basis-mismatch refusal guard**

Append to `tests/rules/importer/iec62477_2022/test_figure_curve_proposals.py`, after `test_none_dimensions_do_not_wildcard`. `pytest`, `select_curve_variant`, `FaultTimeVoltageSelector`, `_figures`, `_variants` and `IDENTITY` all already exist in that file.

```python
@pytest.mark.parametrize("basis", ["ac_rms", "ac_peak"])
def test_figure_7_refuses_a_more_specific_ac_basis(basis: str) -> None:
    """Selection is exact, so the refusal needs no evaluator machinery.

    Figure 7 identifies the variant as AC without specifying RMS or peak, so only its own
    ac_unspecified selector matches. This guards selection, not comparison: it does not
    prove a consumer cannot select ac_unspecified and then compare the returned number
    against an RMS or peak quantity. #36 and #37 add that consumer-level guard when they
    add engineering comparisons.
    """
    rule, _ = project_fault_time_voltage(
        _figures(),
        _variants(0, "a" * 64),
        _variants(1, "b" * 64),
        _variants(2, "c" * 64),
        IDENTITY,
    )
    probe = FaultTimeVoltageSelector(
        subject="conductive_accessible_part",
        voltage_basis=basis,
        dvc_context=None,
        environment_context=None,
    )

    assert select_curve_variant(rule, probe).variant is None
```

- [ ] **Step 4: Run it to verify it passes**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run pytest tests/rules/importer/iec62477_2022/test_figure_curve_proposals.py -k refuses -v
```

Expected: PASS, two parametrised cases. To prove it bites, temporarily add `"ac_unspecified"` to the parametrise list, re-run, see that case fail, then remove it.

- [ ] **Step 5: Commit**

```bash
git add tests/rules/importer/iec62477_2022/test_curve_recipe.py tests/rules/importer/iec62477_2022/test_figure_curve_proposals.py
git commit -m "test(rules): guard the curve slot inventory and the basis refusal

Two regression guards #50 asks for. The slot inventory is now stated per
figure independently of the recipe, so an edit to one figure cannot silently
redefine another, and every declared basis is checked against the model's own
vocabulary.

The refusal guard proves that Figure 7 cannot be selected with ac_rms or
ac_peak, only with its exact ac_unspecified selector. It guards selection,
not comparison; the consumer-level guard belongs to #36 and #37.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Full gates, then the pull request

**Files:** none modified. Verification and delivery only.

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: a PR closing #50, merged before #52 starts.

- [ ] **Step 1: Lint**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 2: Types**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; uv run mypy
```

Expected: `Success: no issues found in <N> source files`.

- [ ] **Step 3: Full suite**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; $env:QT_QPA_PLATFORM = "offscreen"; uv run pytest -n 12 -q
```

Expected: all pass, with the private licensed-document tests skipped. `tests/rules/test_evaluator.py::test_archive_round_trip_does_not_change_evaluation` is a known load-sensitive hypothesis `DeadlineExceeded` that predates this branch — if it fails, re-run it alone to confirm it passes, and report it as a baseline flake rather than fixing or weakening it.

- [ ] **Step 4: Coverage gate**

```bash
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"; $env:QT_QPA_PLATFORM = "offscreen"; uv run pytest -n 12 -q --cov=src/insulation_coordination --cov-fail-under=80
```

Expected: `Required test coverage of 80% reached.`

- [ ] **Step 5: Audit the diff for licensed content**

```bash
git diff origin/main --stat; git diff origin/main | Select-String -Pattern "[0-9]" -Context 0,0
```

Read every numeric hit. Permitted: line numbers, page numbers, `range` bounds, artifact digests, figure numbers, slot counts. Not permitted: any value from a source table or figure. The justification sentence must appear verbatim where it appears at all, with no comparison to any other table or figure attached to it.

- [ ] **Step 6: Push and open the PR**

```bash
git push -u origin worktree-issue-50-figure-7-basis
```

Then open a PR titled `Declare Figure 7's AC basis as unspecified`, body closing #50, stating: the contract change and its one-sentence justification; that the aggregate `dvc.fault_time_voltage` rule's hash changes so a rebuilt package needs renewed review while reviewed geometry does not need re-digitizing; that an existing approved package still loads; that the refusal is structural via exact selector matching; that the consumer-level comparison guard belongs to #36 and #37; and that the private licensed-document tests were skipped locally and need a run where the PDFs live.

- [ ] **Step 7: Ask the maintainer to run the private tests**

The private suite cannot run on this machine. Ask, in the PR:

```bash
$env:ICC_PRIVATE_STANDARDS_DIR = "<directory holding the licensed PDFs>"; uv run pytest -m private_standard -q
```

Do not claim the private tests pass until that output exists.

---

## Self-Review

**Spec coverage:** token vocabulary → Task 1. Figure 7 selector and the public justification wording → Task 2. `dvc.fault_applicability` propagation → Task 2 (asserted, not edited). Package identity and review state → Task 2's commit message and Task 4's PR body. Consumer semantics → Task 1's docstring plus Task 3's refusal guard. Tests, both guards and the four pinned updates → Tasks 2 and 3. Public record rule → Global Constraints, enforced by Task 4 Step 5. Private test handling → Task 4 Steps 3 and 7. Out of scope items appear in no task.

**One spec correction found while writing this plan:** the spec says the private curve inventory test "follows the new variant inventory". It does not — `tests/private/test_iec62477_curves.py` compares canonical hashes and semantic ids only and never asserts a basis, so it needs no edit; it re-verifies determinism against the changed contract. Task 4 treats it as a run-elsewhere obligation rather than an edit.

**Placeholders:** none. Every code step carries the code, every command its expected output.

**Type consistency:** `voltage_basis` is spelled identically in Tasks 1-3; the token is `ac_unspecified` throughout; `_EXPECTED_SLOTS` is defined and used only in Task 3; `select_curve_variant(rule, probe).variant is None` matches the `CurveSelectionResult` shape used by the existing `test_none_dimensions_do_not_wildcard`.
