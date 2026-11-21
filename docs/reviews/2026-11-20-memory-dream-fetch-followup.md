# Memory / Dream / Fetch follow-up review — 2026-11-20

## Scope

Follow-up to PR #36 at `4efd804667b1556b11e22a451b57809ac5ece266`.
This change is code-only and uses synthetic fixtures. It does not start Muse,
invoke a Dream model, enable a Feishu Workflow, read or write a live Bitable,
or send recruiting messages.

## Fixed in this follow-up

- Dream CLI now requires an explicit Human/Bot operator directory at both batch
  start and completion. An empty default directory can no longer silently
  suppress all human feedback or be mistaken for a production identity map.
- Search Dream accepts only `matching_correction / search_match` signals.
  Greeting remains on the greeting-memory publication path; Workflow outcome
  signals are not converted into search keywords or exclusions.
- A Fetch round that starts without Search Memory keeps that exact no-memory
  snapshot. A later publish cannot change the parameters mid-round.
- Dream recovery reloads the complete frozen signal-id set, including signals
  already marked `learned`. It no longer shrinks the batch to only the rows
  still in `pending_dream`.
- Batch checkpoint writes are idempotent. A retry recognizes an identical
  checkpoint and fills only missing empty `source_context` cells; conflicting
  context is never overwritten.
- Empty batches cannot enter Dream completion.
- Legacy `retained` rows are inert when exactly one current `published` row
  exists. More than one published row, or retained-only state, remains blocked
  for explicit reconciliation.

## Deliberately fail-closed

- Multiple history edits to the same watched field remain `unknown` unless
  there is a unique attributable history change. Current Workflow-written
  Human Signals do not carry a stable source event id or before/after pair;
  the implementation must not guess which historical edit caused the row.
- Dream and direct Memory publication now resolve each signal's
  `source_record_id` through the configured Jobs table `candidate_id` field.
  Missing mapping, a non-text live field, or an empty source value fails closed.
  The private Feishu config must map the actual production field id; that live
  mapping has not yet been inspected in this session.
- The operator directory remains private host configuration. No names, IDs,
  tokens, cookies or credentials are committed.

## Verification status

New regression tests are added for the fixes above. This GitHub-connected
editing session cannot execute the repository's Python environment; local
pytest, Ruff and mypy results are therefore pending. The CI workflow was
accepted and triggered, but the observed runs failed before runner allocation:
`runner_id=0`, no runner name and an empty step list. This is not a pytest,
Ruff or mypy result; the execution environment remains blocked.

## Still not live-verified

- Feishu schema and Bitable read/write
- Native history correlation and operator identity on the real Base
- Workflow event subscription
- GPT Dream attribution/model invocation
- Muse Fetch consumption and changed real search parameters
- Cross-process/distributed single-writer behavior


## Third-round disposition — follow-up commit

The following additional code changes are included after the initial follow-up:

- The publish claim is process-wide across independent `SharedMemoryService` instances and keyed by the physical table/domain. `search` and `matching` therefore contend for the same `search_memory` slot.
- In-place updates now re-read after an unverified/partial write. The service restores the previous full row only when every observed field is either its previous value or the attempted value and no unrelated field changed. It then verifies the complete previous row. If the readback is unavailable or a conflicting edit is observed, it does not overwrite that state and reports restoration as unknown/false.
- Dream batches now freeze an explicit 10-business-day window (`window_start`, IANA timezone, and business-day count) into their identity and checkpoint. Signals outside that window remain pending and are not silently consumed.
- A folded Dream with no net change marks its frozen Signals learned without incrementing the current Memory version. An empty net result without a baseline creates no empty Memory row.
- GPT/Muse host reasoning rules are added in `skills/job-hunting/references/memory-dream.md`, including clustering across independent Jobs/days, sequential edits on one Job, baseline preservation, contradictory evidence, and no automatic retirement when a feature leaves the rolling window.
- A regression test explicitly preserves the current fail-closed behavior for two sequential history edits when no event-correlation key exists.

Still blocked and not represented as solved:
- Production Workflow Human Signals do not currently provide a verified source event ID or populated before/after correlation pair. Native history alone cannot safely distinguish multiple edits. The new test documents this; production learning remains blocked for ambiguous rows until a stable event-correlation source is connected.
- The host must hold a candidate-level lease across the entire start → GPT Dream → complete lifecycle and serialize direct publishers. The process-wide Python lock does not coordinate separate CLI processes or machines.
- The actual Jobs `candidate_id` field ID/type must be verified in the private Feishu config and live schema.
- The host must compute `window_start` from its configured work calendar. Without a configured holiday calendar, the reference requires the explicit Monday–Friday fallback; the code validates the frozen boundaries and timezone but does not independently know public holidays or prove the interval contains exactly ten business days.
- Greeting has an isolated publication table and is excluded from Search Dream, but a separate production Greeting aggregation/consumption workflow is not claimed as complete.
- CI runs observed so far still fail before runner allocation (`runner_id=0`, no steps); no pytest/Ruff/mypy result is available from GitHub Actions.

No real Base, Workflow subscription, GPT invocation, Muse Fetch or recruiting action was performed by this follow-up.
