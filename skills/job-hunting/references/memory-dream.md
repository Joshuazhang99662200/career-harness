# Search Memory Dream — Host Instruction

This reference is the reasoning contract for the GPT/Muse host. The repository service validates, freezes, folds and publishes caller-supplied deltas; it does not call a model or decide whether a behavior is a stable preference.

## Observation window

- Each Search Dream observes the most recent **10 completed business days**, not 10 calendar days.
- Compute `window_start` and `cutoff` from the host's configured timezone and business calendar. Pass both as offset-aware ISO-8601 timestamps, together with `window_timezone` and `window_business_days=10`, to `DreamBatchStart`.
- If the host has no holiday calendar, use Monday–Friday as the explicit fallback and record that public holidays were not excluded. Never silently treat 10 calendar days as 10 business days.
- The batch freezes its window and signal IDs. Later signals wait for a later batch. A resumed batch must reuse its original window; do not recalculate it.
- Signals outside the window remain in the source unchanged. Falling outside the observation window does not retire or delete an existing Learned Feature.

## Eligible evidence

Consume only signals already admitted by the service as:
- `signal_type=matching_correction`;
- `memory_domain=search_match`;
- verified Human operator, not Bot or unknown;
- source Job belongs to the requested candidate;
- complete, attributable before/after change;
- `changed_at` within the frozen window.

Never reinterpret `greeting_revision`, `workflow_outcome`, message feedback, a Bot write, an unknown actor, or an unattributed history row as search preference. Greeting Memory is a separate domain and must use its own publisher. Workflow context is operational trace, not a search feature.

If there are no eligible signals, skip the model call and do not create a Dream completion request.

## How to reason over the signals

1. Read the current published Search Memory as the baseline. Do not rebuild from the 10-day window alone.
2. Cluster corrections by the actual feature being changed (role direction, keyword, exclusion or hard preference). Keep each source Signal ID and source Job record attached.
3. Distinguish a repeated preference across independent Jobs/days from multiple sequential edits on one Job. A chain such as C→B→A is two real transitions, but it is one Job context, not two independent Job samples.
4. Classify evidence as stable/repeated, role- or industry-specific, one-off/job-specific, contradictory, or unknown. State the observed counts (Signals, distinct Jobs, distinct days) and cite the supporting Signal IDs. Do not invent a numeric frequency threshold that the owner has not configured.
5. Treat high-frequency behavior as a candidate Learned Feature only when the pattern repeats across independent contexts and is not contradicted by comparable evidence. Preserve exceptions and counterexamples; do not generalize one role's correction to every role.
6. Translate supported changes into the existing `SignalPreferenceDelta` contract. Every frozen Signal must have exactly one delta; a Signal with no net search change gets empty add/remove lists and a concise reason. Keep evidence references and the pattern summary in `reason`.
7. Merge deltas into the existing full baseline. Remove a feature only when an attributable correction explicitly reverses it or the owner-approved policy supports retirement. Never remove a feature merely because it did not recur in the latest 10-day window.
8. Do not change hard constraints, candidate identity, approval, pipeline status, message content or send permissions. GPT proposes search preference deltas; the service owns actor validation, candidate ownership, batch identity and publication.

## Publication and no-op behavior

- Complete a batch only with one delta per frozen Signal ID, no missing or extra IDs.
- The published `jd_digest` is the source job's JD text digest. One source job uses that text digest directly. Several source jobs use a canonical digest of each source record and that job's JD digest. Do not hash the folded keywords, directions or exclusions into this field. A source job with no JD text fails closed.
- If the folded result is identical to the current baseline, mark the Signals learned without incrementing the Memory version. If there is no baseline and no effective search feature, mark the batch as a no-op without creating an empty Memory row.
- A no-op is not a failed Dream. Report `no_change=true`, the current version (if any), the learned/pending Signal IDs, and the evidence summary.
- If attribution, source Job ownership, baseline integrity or write/readback is unknown, fail closed and preserve the previous Memory. Do not manufacture a new feature to make the batch non-empty.
- The host must hold one candidate-level Dream lease across the entire start → model reasoning → complete lifecycle, and serialize direct Memory publication against that lifecycle. The code's process-wide lock covers independent Service instances in one process only; it is not a distributed lock across CLI processes or machines.

## Required host report

Report the frozen 10-business-day window and timezone, eligible/excluded Signal counts with reasons, distinct Jobs/days, stable and contested feature candidates, baseline changes, no-op or published version, exact source Signal IDs, pending writebacks and recovery point. Do not report a successful learning loop until the next Search Fetch round actually consumes the published version.
