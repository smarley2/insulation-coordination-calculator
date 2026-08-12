# Issue #35 — IEC 62477-1:2022 net classification, DVC, and verified galvanic barriers

Execution plan for [issue #35](https://github.com/smarley2/insulation-coordination-calculator/issues/35).
The issue text is the specification; this file is the execution order, plus the decisions taken
where the issue left a gap. Where the two disagree, this file's **Decisions** section wins because
the user ruled on each one.

Branch `worktree-issue-35-net-topology`, based on `origin/main` (aa4e00a, the merge of PR #47).

## Goal

An auditable project-topology model — net classes with orthogonal IEC 62477-1 attributes, galvanic
domains, and verified domain-to-domain barriers — plus an offline guide that explains every option
without choosing the engineer's insulation design.

## Global constraints

These bind every task.

- Support IEC 62477-1:2022 only.
- Do **not** calculate, infer, or recommend a DVC.
- Do **not** automatically choose functional/basic/supplementary/double/reinforced insulation.
- A domain name never proves galvanic isolation. Verified isolation is a property of a pair of
  domains, never a checkbox on one net.
- Classification changes must not alter pair voltages, insulation selections, exclusions, or
  overrides. Pair IDs and keys survive every topology edit.
- Existing IEC 60664 clearance/creepage calculations must remain usable while topology and DVC are
  incomplete. Incomplete topology is a *status*, never a hard failure.
- **Licensed content:** this is a public repository. No value, heading, note, or clause wording from
  an IEC document may appear in any committed file — source, test, fixture, or docstring. Every
  displayed DVC number comes from the active `.icrules` package at runtime. Public tests use
  synthetic packages with invented values (`tests/fixtures/synthetic_rules.py`). Permitted in
  committed files: page numbers, table identifiers, clause numbers, and row/column indexes.
- Every task: focused failing test first, `uv run ruff check .` and `uv run mypy` clean on the
  touched paths, one commit per task with the stated message.

## Decisions (gaps and conflicts resolved before execution)

- **D1 — DVC membership.** `DecisiveVoltageClass` is exactly `NOT_EVALUATED`, `DVC_AS`, `DVC_B`,
  `DVC_C`. The user confirmed IEC 62477-1:2022 defines DVC A-s, B, and C only. Note that
  `rules/importer/recipes/iec62477_1_2022/supply.py` currently declares five designations
  (`dvc_a`…`dvc_d`); that is out of scope here and is tracked separately. Our enum *values* match
  the package's designation strings for the three real classes, so no translation layer is needed.
- **D2 — `galvanic_domain_id` is nullable on `NetClass`.** The issue says a circuit net requires a
  domain, but a `NetClass` is constructed before any domain exists (24 construction sites). So:
  `NetClass.galvanic_domain_id: UUID | None`; `Project` validation rejects a domain id that does not
  resolve; a circuit net with `None` is *incomplete*, not invalid; the migration and the UI's
  add-net path assign the project's direct domain.
- **D3 — Where things live.** All new enums (including the barrier ones) go in
  `domain/enums.py`, beside the existing ones. The immutable models go in `domain/topology.py`.
  `Project` gains two collections the issue does not mention but requires:
  `galvanic_domains: tuple[GalvanicDomain, ...]` and `galvanic_barriers: tuple[GalvanicBarrier, ...]`.
- **D4 — The guide reuses the #29 help machinery.** `ui/voltage_guidance.py` already holds the
  registry pattern (`VoltageGuidance` model with `detailed_text`, `examples`, `common_mistakes`) and
  `ui/help_indicator.py` already provides `HelpIndicator` (hover + keyboard + dialog) and
  `GuidanceDialog`. Topology and DVC guidance registers into that machinery rather than growing a
  second help system.
- **D5 — The DVC row mapping is a single named constant.** `iec62477_2022.dvc.voltage_limits` is a
  `DecisionRule` whose inputs are deliberately positional and anonymous (`dvc-1`…`dvc-4`,
  `voltage-quantity-1`…`voltage-quantity-5`) because the source's own wording may not be committed.
  A consumer therefore needs a class → row-token map. It lives in exactly one module-level constant,
  it is the only place that knowledge exists, and Task 6 must not spread it.

## Interfaces that already exist (read the real signature before using it)

- `domain/project.py`: `FrozenModel` (`extra="forbid"`, `frozen=True`), `NetClass`, `Project` with
  `_requires_consistent_pairs`, `_canonical_pair_key`.
- `project/persistence.py`: `PROJECT_SCHEMA_VERSION = 2`, `migrate_project_document`, `load_project`,
  `save_project_atomic`, `ProjectVersionError`.
- `project/pairs.py`: `reconcile_pairs` — the only thing allowed to touch the pair set.
- `rules/evaluator.py`: `evaluate_decision(rule, inputs) -> DecisionResult` with
  `status in {"matched", "no_match", "input_required"}`; `select_curve_variant`,
  `evaluate_piecewise_curve`.
- `domain/rules.py`: `RulePackage(manifest, tables, formulas, mappings, decisions, procedures,
  guidance, curves, …)`. A rule's `id` *is* its semantic id.
- `rules/importer/iec62477_2022/semantic_ids.py`: `DVC_VOLTAGE_LIMITS`, `DVC_PROTECTION_MATRIX`,
  `DVC_FAULT_TIME_VOLTAGE` (+ `.impulse_reference`, `.fault_time_reference`, `.not_applicable`
  sub-rules derived from `DVC_VOLTAGE_LIMITS`).
- `ui/project_pages.py`: `ProjectPage`, `project_changed` signal, `_update_project(**updates)`,
  `add_net_class`, `_labelled(text, help_indicator)`.
- `ui/help_indicator.py`: `HelpIndicator`, `GuidanceDialog`, `FieldStateBadge`.
- `report/model.py`: `ReportModel`, `build_report_model`, `RulesProvenance`.

## Task 1 — Enums, immutable topology models, and project validation

Adds the domain layer. No UI, no persistence, no report.

**Files:** `src/insulation_coordination/domain/enums.py` (modify),
`src/insulation_coordination/domain/topology.py` (create),
`src/insulation_coordination/domain/project.py` (modify),
`tests/domain/test_topology.py` (create).

**Enums** — add to `domain/enums.py`, exact members and values:

```python
class NetClassType(StrEnum):
    CIRCUIT = "circuit"
    PE_BONDED_CONDUCTIVE_PART = "pe_bonded_conductive_part"
    ACCESSIBLE_CONDUCTIVE_PART = "accessible_conductive_part"
    ACCESSIBLE_INSULATING_SURFACE = "accessible_insulating_surface"


class CircuitSourceRelationship(StrEnum):
    MAINS_CONNECTED = "mains_connected"
    NON_MAINS_EXTERNAL = "non_mains_external"
    INTERNALLY_GENERATED = "internally_generated"


class ConnectionExposure(StrEnum):
    INTERNAL_ONLY = "internal_only"
    EXTERNAL_LOCAL_PORT_OR_CABLE = "external_local_port_or_cable"
    LONG_OUTDOOR_LINE = "long_outdoor_line"


class DecisiveVoltageClass(StrEnum):
    NOT_EVALUATED = "not_evaluated"
    DVC_AS = "dvc_as"
    DVC_B = "dvc_b"
    DVC_C = "dvc_c"


class ReviewState(StrEnum):
    NEEDS_REVIEW = "needs_review"
    USER_CONFIRMED = "user_confirmed"


class BarrierVerificationStatus(StrEnum):
    NOT_EVALUATED = "not_evaluated"
    NO_GALVANIC_ISOLATION = "no_galvanic_isolation"
    VERIFIED_GALVANIC_ISOLATION = "verified_galvanic_isolation"


class VerificationMethod(StrEnum):
    TEST = "test"
    CALCULATION = "calculation"
    SIMULATION = "simulation"
    DOCUMENT_REVIEW = "document_review"
```

**Models** — `domain/topology.py`, both subclassing the existing `FrozenModel` from
`domain/project.py`:

```python
class GalvanicDomain(FrozenModel):
    id: UUID
    name: str  # min_length=1
    description: str = ""
    is_direct_source_domain: bool = False
    review_state: ReviewState = ReviewState.NEEDS_REVIEW


class GalvanicBarrier(FrozenModel):
    id: UUID
    domain_a_id: UUID
    domain_b_id: UUID
    status: BarrierVerificationStatus
    description: str
    verification_method: VerificationMethod | None = None
    evidence_reference: str | None = None
    notes: str = ""
```

`GalvanicBarrier` validation, on the model:

- `domain_a_id != domain_b_id`.
- `VERIFIED_GALVANIC_ISOLATION` requires a `verification_method` and a non-blank
  `evidence_reference`.
- `NO_GALVANIC_ISOLATION` and `NOT_EVALUATED` require both verification-only fields to be `None`
  (the editor clears them; the model refuses to hold them).
- Expose the unordered key — `sorted((str(a), str(b)))` — as a property, so the project validator and
  the editor cannot disagree about what "the same barrier" means.

**`NetClass` fields** — added with defaults so the existing 24 construction sites keep working:

```python
net_type: NetClassType = NetClassType.CIRCUIT
source_relationship: CircuitSourceRelationship | None = (
    CircuitSourceRelationship.INTERNALLY_GENERATED
)
connection_exposure: ConnectionExposure | None = ConnectionExposure.INTERNAL_ONLY
decisive_voltage_class: DecisiveVoltageClass | None = DecisiveVoltageClass.NOT_EVALUATED
galvanic_domain_id: UUID | None = None
classification_review_state: ReviewState = ReviewState.NEEDS_REVIEW
```

Model validation: a non-circuit net requires all four circuit-only fields to be `None`; a circuit
net requires the three enum fields to be set (see D2 — the domain may be `None`). Net names stay
independent of classification.

**`Project` fields and validation:** add `galvanic_domains: tuple[GalvanicDomain, ...] = ()` and
`galvanic_barriers: tuple[GalvanicBarrier, ...] = ()`. Extend the existing validator (do not add a
competing one) with: domain ids unique; domain names unique after whitespace-and-case
normalisation; at most one `is_direct_source_domain`, and exactly one when any domain exists; every
`NetClass.galvanic_domain_id` resolves to a declared domain; every barrier's two domains resolve;
no two barriers share an unordered key. A project with no domains at all stays valid — that is the
state a legacy project loads in before migration fills it.

**Helpers** (this is the interface #36 and #37 consume — keep the names):

```python
def circuit_nets(project: Project) -> tuple[NetClass, ...]: ...
def domain_for_net(project: Project, net_id: UUID) -> GalvanicDomain | None: ...
def barrier_between(project: Project, a: UUID, b: UUID) -> GalvanicBarrier | None: ...
def topology_completion(project: Project) -> TopologyCompletion: ...
```

`TopologyCompletion` is a `FrozenModel` reporting what is unresolved, deterministically ordered:
nets needing review, circuit nets without a domain, circuit nets whose DVC is `NOT_EVALUATED`,
domain pairs with no barrier, and barriers that are `NOT_EVALUATED`. It carries an `is_complete`
property. It must never raise.

**Tests** (`tests/domain/test_topology.py`) — one focused test per rule above, plus: constructing a
`NetClass` with only `id` and `name` still works and lands on the documented defaults; a
non-circuit net with a DVC is rejected; A-B and B-A count as one barrier; `topology_completion` on
an empty-topology project reports incomplete without raising.

**Verify:** `uv run pytest tests/domain/test_topology.py tests/project -q`, `uv run mypy`.

**Commit:** `feat: add net topology domain models`

## Task 2 — Project persistence and migration

**Files:** `src/insulation_coordination/project/persistence.py` (modify),
`tests/project/test_persistence.py` (extend).

Bump `PROJECT_SCHEMA_VERSION` to 3 and extend `migrate_project_document` in the existing style
(chained: 1 → 2 → 3, so a version-1 document still loads). A version-2 document migrates to:

- one new `GalvanicDomain` with a fresh UUID, `is_direct_source_domain=True`, and a neutral name
  (e.g. `"Direct / source-side domain"`);
- every net: `net_type=circuit`, `source_relationship=internally_generated`,
  `connection_exposure=internal_only`, `decisive_voltage_class=not_evaluated`,
  `galvanic_domain_id` = that domain, `classification_review_state=needs_review`;
- `galvanic_barriers` empty.

Migration must reject a version-2 document that already carries topology keys, exactly as the
version-1 branch rejects a document that already has `group_splits`.

**Tests:** a pre-feature (schema 2) fixture document migrates with every net id, pair id, pair key,
stress, override, exclusion, note, and default byte-identical; migrated classifications are
`needs_review`, never `user_confirmed`; load → save → load is equal, and the second load neither
creates a domain nor changes any UUID; a schema-1 document still loads through both steps.

**Verify:** `uv run pytest tests/project/test_persistence.py -q`, `uv run mypy`.

**Commit:** `feat: migrate projects to topology schema`

## Task 3 — Net-class classification controls

The first UI task. It also does the small generalisation the guide needs (D4).

**Files:** `src/insulation_coordination/ui/net_class_classification.py` (create),
`src/insulation_coordination/ui/topology_guidance.py` (create),
`src/insulation_coordination/ui/voltage_guidance.py` (modify, minimally),
`src/insulation_coordination/ui/help_indicator.py` (modify, minimally),
`src/insulation_coordination/ui/project_pages.py` (modify),
`tests/ui/test_net_class_classification.py` (create).

**Guidance machinery.** `HelpIndicator` and `guidance_for` are typed to `VoltageGuidanceId` today.
Widen them to accept any `StrEnum` id and add a registration function so another module can
contribute entries to the same registry. Do not rename `VoltageGuidanceId`, do not duplicate
`GuidanceDialog`, and do not break `tests/ui/test_voltage_guidance.py` or
`tests/ui/test_help_indicator.py`.

`ui/topology_guidance.py` holds one guidance entry per option of the five classification enums
(and per barrier status). Each entry must state: definition, when to select, when not to select,
what it affects, what it does **not** affect, examples, and common mistakes. Text is this
application's own engineering guidance — it paraphrases no standard and quotes no clause. Where an
option's consequence is a rule-package matter, say which semantic rule decides it rather than
stating a number.

**Widget.** A focused `QWidget` for the selected net, dropdowns in this exact order: Net class type,
Source relationship, Connection exposure, DVC, Galvanic domain. Each carries a `HelpIndicator`, and
the panel carries a **How to choose** button opening the guidance dialog. DVC options are exactly
Not evaluated, DVC A-s, DVC B, DVC C.

Behaviour: circuit → all fields enabled; non-circuit → circuit fields disabled, showing `N/A`, and
persisting `None`. Any user edit sets `classification_review_state=USER_CONFIRMED`. One edit emits
exactly one project update carrying an immutable replacement `NetClass`, and touches nothing else
in the project. The widget contains no IEC decision logic and never derives a DVC.

Wire it into `ProjectPage` beside the net list, driven by the existing selection signal, and route
its updates through the existing `_update_project`. `ProjectPage.add_net_class` assigns the
project's direct domain to the new net (D2); if the project has no domain yet, leave it `None`.

**Tests:** every enabled/disabled/N/A state; circuit → non-circuit → circuit round trip restores
enum defaults and leaves no stale value; one edit produces one `project_changed` emission; pair data
is byte-identical across a classification edit; the DVC dropdown offers exactly four entries.

**Verify:** `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_net_class_classification.py tests/ui/test_project_pages.py tests/ui/test_voltage_guidance.py tests/ui/test_help_indicator.py -q`, `uv run mypy`.

**Commit:** `feat: add net classification controls`

## Task 4 — Galvanic domain editor

**Files:** `src/insulation_coordination/ui/galvanic_domains.py` (create),
`src/insulation_coordination/ui/project_pages.py` (modify),
`tests/ui/test_galvanic_domains.py` (create).

Put every project transformation in pure module-level functions taking and returning a `Project`,
and keep the widget thin — the tests for the rules must not need a Qt event loop.

Actions: add, rename, edit description, set-direct-domain, and remap-and-delete. Deleting a
referenced domain follows: list the referencing nets and barriers → require a replacement domain →
preview every remap → apply **one** immutable project update → pair IDs and contents unchanged.
Renaming preserves the UUID. Duplicate names (after whitespace/case normalisation) are refused with
a message, not silently de-duplicated. Setting a new direct domain clears the previous one in the
same update.

**Tests:** add, rename, duplicate rejection, direct-domain enforcement, remap-delete preview
content, and a 64-net project where a remap-delete emits exactly one project update.

**Verify:** `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_galvanic_domains.py tests/ui/test_project_pages.py -q`, `uv run mypy`.

**Commit:** `feat: manage galvanic domains`

## Task 5 — Verified barrier editor

**Files:** `src/insulation_coordination/ui/galvanic_barriers.py` (create),
`src/insulation_coordination/ui/project_pages.py` (modify),
`tests/ui/test_galvanic_barriers.py` (create).

Same shape as Task 4: pure transformations plus a thin table widget. Columns: Domain A, Domain B,
Status, Verification method, Evidence/reference, Description.

The editor carries a visible **Verified galvanic isolation** toggle. Checking it selects
`VERIFIED_GALVANIC_ISOLATION` and requires an evidence reference and a method before the change can
be applied. Unchecking asks the user which state now holds — `NOT_EVALUATED` or
`NO_GALVANIC_ISOLATION` — and never silently picks one. Adding a barrier for a pair that already
has one is refused (A-B and B-A are the same pair). Barrier ids are stable across every edit.

Verified isolation grants no attenuation and no protection claim here; #36 owns any such rule.

**Tests:** unordered duplicate rejection, evidence requirement, the explicit uncheck choice
(including cancel leaving the project untouched), stable ids across edits, and a barrier edit
leaving every pair voltage and insulation selection unchanged.

**Verify:** `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_galvanic_barriers.py -q`, `uv run mypy`.

**Commit:** `feat: manage verified galvanic barriers`

## Task 6 — DVC guidance service and guide

**Files:** `src/insulation_coordination/ui/dvc_guide.py` (create),
`src/insulation_coordination/domain/dvc.py` or a service module of the implementer's choosing
(create), `tests/ui/test_dvc_guide.py` (create), plus a synthetic-package fixture.

A service reads DVC facts from the **active approved package** and never from a constant:

```python
class DvcGuidanceService:
    def limits(self, dvc: DecisiveVoltageClass) -> DvcLimitSummary: ...
    def protection_relationships(
        self, dvc: DecisiveVoltageClass
    ) -> tuple[ProtectionGuidance, ...]: ...
```

It queries `iec62477_2022.dvc.voltage_limits`, `iec62477_2022.dvc.protection_matrix`, and
`iec62477_2022.dvc.fault_time_voltage` through `evaluate_decision` / the curve helpers. Every
displayed number carries its `SourceReference`. A missing rule, a wrong-edition package, or an
unapproved package produces a stated "not available from the active package" result — never a
fallback number and never a crash. `NOT_EVALUATED` has no limits to show and must say so.

See D5: the class → `dvc-N` row-token map is one module-level constant, documented as a layout fact
about the source table, and it is the only place that mapping exists. **The row order is an open
question — ask before hard-coding it.**

The guide itself explains, in the application's own words: single pulses are evaluated against the
DC limit; repetitive pulses against the AC limits; abnormal and single-fault voltages follow the
applicable time-voltage behaviour rather than the fixed normal-operation limits alone; and DVC A-s,
B, and C are engineer-selected classifications, not calculator recommendations. It works offline, is
keyboard reachable, and is searchable.

For DVC B it shows the normal-operation limits — AC RMS, AC peak, DC mean, and the impulse withstand
voltage from the applicable Table 7 system-voltage/OVC rule — **read from the package**. No IEC
number appears in any committed file; the public test asserts against a synthetic package whose
values are invented.

**Tests:** synthetic-package limits render with their sources; a package missing the DVC rules
degrades with a stated reason; a wrong-edition package is refused; `NOT_EVALUATED` shows no limits;
the guide opens and is navigable offscreen.

**Verify:** `QT_QPA_PLATFORM=offscreen uv run pytest tests/ui/test_dvc_guide.py -q`, `uv run mypy`.

**Commit:** `feat: add DVC guidance`

## Task 7 — Report integration

**Files:** `src/insulation_coordination/report/model.py` (modify), report templates (modify),
`tests/report/*` (extend).

Extend `ReportModel` with net classification per net, DVC and review status, the domain inventory,
the barrier and evidence inventory, and the unresolved-topology warnings from
`topology_completion`. Tables render deterministically, in the order the helpers already define.

Do not add topology to a pair trace — no calculation consumes it yet, so it belongs in project
metadata. A legacy project with no topology, or one whose DVC is `NOT_EVALUATED`, must still produce
a complete distance report; the topology section states what is unresolved.

**Tests:** classifications, domains, barriers, and evidence appear; unresolved status is stated; a
project with empty topology still builds a report.

**Verify:** `uv run pytest tests/report -q`, `uv run mypy`.

**Commit:** `feat: report project topology`

## Task 8 — Required examples and the end-to-end gate

**Files:** `tests/fixtures/` (extend with structured topology examples), `tests/test_end_to_end.py`
(extend), guidance text (extend where an example belongs beside its option).

Three example topologies, as fixtures and as guide content:

- **Wireless power charging:** mains input, DC link, primary switching/resonant nodes, receiver
  coil/rectifier, battery/DC output, PE enclosure, accessible polymer cover, separate primary and
  receiver domains, and an explicit primary-to-receiver barrier.
- **OBC, isolated and non-isolated variants:** AC input, PFC/DC link, transformer primary, HV
  battery output, 12 V/CAN, chassis. Displayed with this warning: *OBC is a topology example only.
  IEC 62477-1:2022 excludes electric-vehicle electrical equipment/systems; the applicable EV/OBC
  product standard takes precedence.*
- **Variable-speed drive:** mains phases, DC bus, inverter nodes, U/V/W motor output with
  external-cable exposure, control/fieldbus port, PE/heatsink/enclosure, optional isolated-control
  domain.

Each fixture must be a valid `Project`: legal enum combinations, resolvable domains, exactly one
direct domain, no duplicate barriers. No licensed value appears in any of them.

End-to-end: save/reopen each example unchanged; pair copy/paste regression; report build; and the
`circuit_nets` / `domain_for_net` / `barrier_between` / `topology_completion` interfaces that #36 and
#37 will consume.

**Verify (controller runs the full gate, not the subagent):** `uv run ruff check .`,
`uv run mypy`, `QT_QPA_PLATFORM=offscreen uv run pytest -n 12`, then the coverage run with
`--cov-fail-under=80`.

**Commit:** `test: validate IEC 62477 project topology`

## Non-goals

No DVC assistant. No automatic insulation or protection selection. No impulse/TOV calculation (#36).
No dielectric schedule (#37). No wireless-charging EMF assessment.
