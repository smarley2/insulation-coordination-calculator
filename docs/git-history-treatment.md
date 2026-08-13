# Git-history treatment for licensed-content findings

Issue #40, Task 10. Removing licensed content from the current tree does not
remove it from Git history: every commit that ever contained a finding from
`docs/licensed-content-audit.md` remains reachable in clones, forks, and the
GitHub web UI. This document lays out the options and a recommendation. The
decision is the maintainer's and is explicitly **not** made here.

## What is in history

- No licensed PDF, `.icrules`, `.icproj`, or audit export was ever committed
  (verified across all refs). The exposure is limited to the text findings
  inventoried in the audit document: option series, a preferred-level series,
  factors/thresholds, fixture axes/cells, source-like recipe headings, and
  generated report values.
- The exposure is fragments of derived values, not scans or reproductions of
  the standards themselves. Each fragment is small relative to any one
  standard, but the pairing of values with table identifiers is exactly what
  the content policy forbids going forward.
- The repository is public; the history is already replicated in any existing
  clone or fork regardless of what happens to this repository.

## Options

### 1. Current-tree cleanup only (leave history)

Fix findings A-H in new commits; history keeps the old blobs.

- Pros: zero operational risk; no SHA invalidation; existing clones, PR
  references, issue links, tags, and the commit-anchored docs under
  `docs/superpowers/` stay valid; no coordination needed.
- Cons: the removed fragments stay retrievable by anyone who digs through
  history; "we removed it" is only true for the tip.

### 2. History rewrite with `git filter-repo`

Rewrite the offending paths/blobs out of all history, force-push, and
re-point tags.

- Pros: the published repository itself no longer serves the fragments at any
  ref; strongest statement of intent short of deleting the repository.
- Cons: every commit SHA after the earliest touched commit changes (~most of
  the 387-commit history, since findings date to the first weeks); all open
  and merged PR diffs, issue cross-references by SHA, plan/spec documents that
  cite commits, and every clone/worktree break or need re-cloning; forks and
  existing clones still hold the old objects, so the content is reduced, not
  erased; squash-merge SHAs referenced in MEMORY/docs become dangling; a
  mistake during the rewrite is itself hard to undo. GitHub also keeps
  old objects reachable by SHA in caches/fork networks until Support
  intervenes, so option 2 without option 3 is incomplete.

### 3. Rewrite plus GitHub Support purge

Option 2, followed by a GitHub Support request to drop cached views,
dereference the old objects in the fork network, and run garbage collection.

- Pros: the most complete removal available on GitHub; old SHAs stop
  resolving on github.com.
- Cons: all costs of option 2, plus an external dependency with turnaround
  time; still cannot reach clones that were taken before the purge.

## Recommendation (not a decision)

Recommend **option 1 (current-tree cleanup only)**, revisited only if a
rights-holder raises a concern.

Reasoning: the historical exposure is fragmentary derived values rather than
reproductions of the standards; the practical benefit of a rewrite is small
because existing clones and forks retain the objects anyway; and the cost is
concentrated exactly where this project keeps its audit trail — commit-SHA
references in plans, specs, issues, and squash-merge bookkeeping. Cleaning
the tip, keeping the scanner in front of future commits, and documenting the
inventory (this slice) addresses the forward-looking obligation. If the
maintainer's licence review concludes the historical fragments are themselves
a compliance problem, go directly to option 3 — option 2 alone leaves the
content reachable on GitHub and pays the full disruption cost for a partial
result.

If a rewrite is ever chosen, it must run as a separately reviewed operational
plan: freeze merges, enumerate blobs from the audit inventory, rehearse on a
mirror, coordinate the force-push and tag updates, then file the Support
request — never as a side effect of normal implementation work (see the
issue's explicit instruction).

## Decision record

- [ ] Maintainer decision: cleanup-only / rewrite / rewrite + Support purge
- Decided by:
- Date:
- Notes:
