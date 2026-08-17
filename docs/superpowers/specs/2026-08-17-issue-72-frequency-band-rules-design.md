# Issue #72 — the Annex F band grid becomes a rule

The annex's band grid was extracted, reviewed and archived as comparison evidence, and no rule
resolved anything from it. A consumer asking *"my fundamental frequency is X — what factor
applies?"* got no answer, because the recipe declared the grid comparison-only: unlike the two
grids beside it, it restates no approved IEC 60664-4 rule, so it was recorded with no
cross-standard claim and therefore with no claim at all.

Its axis is the reason it stayed inert. The axis cells state a band between two bounds rather
than one number, so the generic numeric parser cannot type them, and the recipe refused to
guess a numeric axis out of them. That refusal is correct and stays. What changes is that the
band now has a typed representation the reviewer confirms, so the grid can be projected without
anything guessing and without any boundary being declared in this repository.

This adds no cross-standard claim. Tables F.1 and F.3 remain comparison evidence for the
already-approved rules they restate, and no comparison names the band grid.

## The typed band

`axis_selectors.py` gains a fourth member of the `AxisSelector` union:

```text
FrequencyBandSelector    lower_hz, upper_hz, inclusive_bound
inclusive_bound          "lower" | "upper" | "both" | "neither"
```

It is an axis selector rather than a mechanism of its own, so everything #53A built for a
reviewed axis reading applies to it unchanged: one proposal per position, a per-position
evidence digest, the exact-review currency test, the duplicate-selector refusal, the approval
blocker, and the review surface beside the row it describes.

Two properties of the band are what the issue is about:

- **The bounds are extracted, never declared.** `parse_frequency_band` reads a cell as one
  quantity, two comparisons pointing the same way, and a second quantity — nothing else is
  accepted — and scales both bounds with the SI prefix the axis column's own header states.
  Both halves come from the document.
- **Inclusivity is typed, not inferred.** The comparison the source writes at each end decides
  which end the band closes, and the projected matcher carries that as `minimum_inclusive` /
  `maximum_inclusive`. A frequency sitting exactly on a boundary lands in the one band the
  source puts it in rather than in whichever row is tried first.

A cell stating anything else — one bound, three, comparisons pointing opposite ways, bounds
that do not increase, or a header with no scaled unit — proposes nothing, and the position
reaches the reviewer unread rather than as a guessed band.

Runtime text matching was never an option: matching prose at resolution time would let a
reprint's rewording silently change which factor applies.

## Reviewing a band

The reviewer confirms a band in the raw grid review dialog, on the row it describes, exactly as
every other axis position is confirmed. The editor splits a selector's dimensions in two:

- Dimensions with a closed vocabulary stay combos built from the model's own `Literal`
  annotations — for a band that is `inclusive_bound`, which the reviewer can correct.
- Dimensions that are quantities are shown read-only and ride through from the proposal. A
  reviewer who could type a bound would be declaring a boundary rather than confirming one, and
  a position nothing was read from carries no bounds and can never be confirmed.

Correcting a misread bound is therefore a raw-cell correction, which moves that position's own
evidence digest and re-opens its review — the same path any other misread axis reading takes.

Because the band cells are read as an axis selector, they are exempt from the
retype-as-a-number raw-cell review item. Extraction derives that exemption from the declared
axis selectors rather than from any one table's coordinates: a cell an axis position reads its
selector from is reviewed as that selector.

## The identifier and the rule

```text
iec62477_2022.high_frequency.band_factor
```

A sibling of `HIGH_FREQUENCY_APPLICABILITY`, not a route under it, for the reason the two Annex
E identifiers are siblings: neither is a route of the other. Applicability answers whether the
annex governs a spacing at all; the band grid answers which factor a frequency falls under.
`REQUIRED_SEMANTIC_IDS` and the required source inventory go from twenty-six entries to
twenty-seven, and the new item names issue #36 as its consumer.

The grid spec is renamed to that identifier and registers a grid projector, so
`package_expectations` files it under `projected_rule_ids` with its one declared route. The two
restated grids keep their `…applicability.annex_f1` / `…annex_f3` identifiers and stay
comparison evidence.

The projected decision takes one numeric input — the same `working_voltage_frequency_hz` the
applicability decision already answers — and returns one numeric `band_factor`. It is
deliberately **not exhaustive**: the source declares bands over part of the frequency range and
says nothing about the rest, so a frequency outside every declared band resolves to `no_match`
and the consumer is told the table settles nothing there. It is never handed the nearest band's
factor.

Two reviewed bands that overlap are refused at projection. `evaluate_decision` serves the first
row that fits, so an overlap would pick a factor by row order rather than by what the source
says; bands meeting at a bound both ends close are an overlap however narrow.

## Contract impact and the rebuild lifecycle

**`IEC_IMPORTER_VERSION` goes from `iec-pdf-8` to `iec-pdf-9`.** Assigned in merge order at
implementation time: issue #60 owns `iec-pdf-7`, the #53B stack owns `iec-pdf-8`, and this
change stacks on that branch and merges after it. The #53C spec's contract-impact section
records `iec-pdf-9` as its own current expectation while stating that its number is decided
when it is implemented; that expectation moves to the next number.

Three separate reasons, any one of which alone would require the bump:

- The band grid is extracted under a different semantic identifier, so its raw grid id and the
  draft's content digest change.
- Its axis cells now carry reviewed typed bands, which the draft did not carry before.
- The package gains a decision rule that no earlier package could have held.

There is no shim and no migration. A trusted approved IEC package built by an older importer
fails `validate_rule_package`'s `importer_version` check, and the identifier sets
`_require_resolved_recipe_semantics` derives from the current recipes no longer match a package
carrying the old band grid id. Both are the intended behaviour.

A rebuild has to:

1. Re-extract from the licensed PDFs. The band grid arrives under the new identifier with one
   axis proposal per band row.
2. Confirm every band in the raw grid review dialog. Approval blocks on any position without
   one exact current review, naming the grid and the position.
3. Re-review the projected rule proposal, then re-approve and re-export.

No source geometry changes: the bounding boxes, row and column counts, and row classifications
are the ones already measured, so a rebuild re-extracts the same regions and the reviewer's work
is the band confirmations and the one new rule proposal, not a fresh pass over the annex.

## Testing

Public and synthetic throughout. Every band and every factor in a fixture is invented; the
licensed bounds and factors are read from the document at import time.

- The band grammar, one case per accepted shape and one per refused shape, including a header
  that states no scaled unit and a scale that changes with the prefix the header states.
- One proposal per band row, each bound to its own cell's evidence, and a cell stating no band
  proposing nothing.
- The full reviewed path: propose, confirm, resolve.
- A frequency inside a band resolving that band's factor; a frequency outside every band
  answering `no_match`; a frequency on an open bound answering `no_match` while the closed bound
  answers its band.
- Overlapping and touching bands refused, and a band with no numeric factor beside it refused.
- The review surface: a band position offering only its inclusivity choice, confirming exactly
  the extracted bounds, and a band nothing was read from staying unconfirmable.

Private, licensed: the end-to-end round trip resolves a factor for every band the reviewed rule
carries, reading each band's own interval off the rule rather than naming one, and answers
`no_match` for one hertz.
