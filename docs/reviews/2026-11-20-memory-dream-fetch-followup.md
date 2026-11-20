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
pytest, Ruff and mypy results are therefore pending. A GitHub Actions workflow
is added to run those gates on the PR. No test result is claimed until Actions
returns an actual run and conclusion.

## Still not live-verified

- Feishu schema and Bitable read/write
- Native history correlation and operator identity on the real Base
- Workflow event subscription
- GPT Dream attribution/model invocation
- Muse Fetch consumption and changed real search parameters
- Cross-process/distributed single-writer behavior
