# Figure 7's AC basis becomes `ac_unspecified` (Issue #50)

Issue: [#50](https://github.com/smarley2/insulation-coordination-calculator/issues/50).
Date: 2026-08-11. First of the chain #50 → #52 → #53 → PR #55.

## Purpose

The Figure 7 curve variant declares `voltage_basis="ac_peak"`. Figure 7 identifies the
variant as AC without specifying RMS or peak. The declared basis is therefore an assertion
the source does not make, in an approved-package contract that #35, #36 and #37 consume.

This design replaces it with a fourth basis token, `ac_unspecified`, so the contract states
what the source states and nothing more, and so a consumer cannot obtain the curve by
presenting an RMS or a peak quantity.

Same defect class as the invented DVC designations removed in #48: a value in a contract
that the document does not carry.

## Decision

- Figure 5: `dc`
- Figure 6: `ac_peak`
- Figure 7 DC variant: `dc`
- Figure 7 AC variant: **`ac_unspecified`**

Figures 5 and 6 state their basis explicitly and do not move.

`ac_unspecified` rather than a plain `ac` token: a bare `ac` invites a later reader to
supply the missing half by convention — "generic AC, therefore RMS". `ac_unspecified` makes
the limitation executable instead of advisory.

`ac_unspecified` inside the selector rather than a parallel `basis_stated: bool` flag: a
flag permits the contradictory state `voltage_basis="ac_peak", basis_stated=False`. The
ambiguity belongs to the variant's identity.

**Maintenance rule.** Nobody may narrow `ac_unspecified` to `ac_rms` or `ac_peak` without
new explicit normative evidence stating the more specific basis for that figure.

## Token vocabulary

`FaultTimeVoltageSelector.voltage_basis` in `domain/rules.py`:

```python
voltage_basis: TypingLiteral["ac_rms", "ac_peak", "ac_unspecified", "dc"]
```

`ac_rms` stays. It is already part of the public model contract and is used by existing
synthetic and review tests; removing it would be an unrelated contract change.

The model records the meaning of the new token and the maintenance rule above.

## Propagation into `dvc.fault_applicability`

`recipes/iec62477_1_2022/clauses.py` derives that rule's vocabulary from the curve recipes
rather than declaring it, so the change propagates without editing that module:

- `voltage_basis` allowed values: `("dc", "ac_peak")` → `("dc", "ac_peak", "ac_unspecified")`;
- the `conductive_accessible_part` row's basis matcher moves from `ac_peak` to
  `ac_unspecified`.

The clause fragment's structural contract is unaffected. No other rule references the
Figure 7 selector.

## Package identity and review state

`project_fault_time_voltage` builds one aggregate `iec62477_2022.dvc.fault_time_voltage`
rule covering Figures 5 to 7 and one semantic proposal for that rule, whose
`source_artifact_sha256` aggregates the figure artifact digests separately from the rule
hash.

Changing the Figure 7 selector changes the canonical hash of the aggregate rule and
therefore produces a new semantic proposal and package digest. The rebuilt semantic rule
requires renewed review and approval. The already-reviewed curve geometry and source
artifacts do not require re-digitization solely because the selector identity changed.

Variant ids are positional (`…dvc.fault_time_voltage.7.2`) and do not move.

Following #48's precedent, an already-approved package carrying the old selector stays
internally consistent and still loads, because `ac_peak` remains a valid token. No
migration, and no rewriting of stored review state.

## Consumer semantics

`select_curve_variant` matches selectors exactly. A consumer probing Figure 7 with
`ac_peak` or `ac_rms` gets `no_match`, not a wrong curve, so the refusal needs no new
evaluator machinery, guard clause or comparison veto.

`ac_unspecified` is a source-contract identity, not a wildcard. A consumer that knows its
engineering quantity is RMS or peak must submit `ac_rms` or `ac_peak` respectively, and
must not coerce that input to `ac_unspecified` merely to obtain the Figure 7 curve. The
evaluator cannot prevent a future consumer from deliberately asking for `ac_unspecified`;
it only guarantees that RMS and peak selectors never silently match it. That obligation
travels to #53, #36 and #37.

The curve-review page prints `selector.voltage_basis` verbatim in its trace-recovery
prompt, so a reviewer recovering Figure 7 will read `ac_unspecified` there. No token label
map exists in that page today and this design does not add one; the raw token is accurate
and unambiguous.

Nothing in PR #55 selects a curve variant — `domain/dvc.py` renders the fault-time cell as
a reference to `dvc.fault_time_voltage` and never probes it — so this change does not touch
the #35 adapter.

## Tests

Public:

- the Figure 7 basis assertion in the curve-recipe test becomes `("dc", "ac_unspecified")`;
- both Figure 7 selector probes in the figure-proposal tests move to `ac_unspecified`,
  including the one that must *not* match: it exists to prove that a wrong `dvc_context`
  defeats a match, so it keeps the correct basis and varies only the context. Leaving it on
  `ac_peak` would make it fail for two reasons at once and stop isolating the context
  dimension;
- the DVC clause projection test covers the widened allowed values and the moved row;
- **variant inventory guard**: every curve spec's declared bases are checked against the
  model's token vocabulary, and each figure's slot inventory is asserted independently, so
  an edit to one figure cannot silently redefine another;
- **basis-mismatch refusal guard**: Figure 7 cannot be selected using `ac_rms` or
  `ac_peak`; only its exact `ac_unspecified` selector matches.

The refusal guard proves selection, not comparison. It does not prove that a consumer
cannot select `ac_unspecified` and then compare the returned number against an RMS or peak
quantity. When #36 and #37 add engineering comparisons, they add the consumer-level test
that a known RMS or peak quantity is never coerced to `ac_unspecified`.

Private: no edit. `tests/private/test_iec62477_curves.py` compares canonical hashes and
stable semantic identities and never asserts a basis, so it re-verifies determinism against
the changed contract as it stands. It skips where no licensed standards directory is
configured, so the maintainer runs it and reports the result.

## Public record

The only justification committed to this repository, its tests, its commit messages, the
issue or the pull request:

> Figure 7 identifies the variant as AC without specifying RMS or peak. Therefore the
> semantic contract uses `ac_unspecified` and consumers must not infer a more specific
> basis.

Maintainer review evidence beyond what the source explicitly states or does not state is
not recorded here, in any form, numberless or otherwise.

## Out of scope

- Any change to Figure 5 or Figure 6.
- Removing or renaming `ac_rms`.
- Consumer-side engineering comparison rules (#36, #37).
- #52's Annex E semantic id split, and #53's Table 2 and Table 3 selector contracts.
