# Signal → Memory simplification audit and plan — 2026-11-20

Audit only. No product code was changed in the commit that adds this file.
The tree under review is `1a4737e0747becfe466a99bf25782453ce06731f`.
This session did not read or write a live Feishu Base, did not enable a Workflow, did not run Fetch, ingest, outreach, Muse, or Dream against live data, and did not open a pull request.

Live Bitable schema was not inspected. Where the repo does not name a field, the live column is **UNVERIFIED**. Table ids already committed in `src/jobagent/schemas/shared_memory.py` are cited. No base token is recorded here.

## A. Git protection

| Item | Value |
|---|---|
| Repo path | `/workspace` |
| Starting checkout | detached `HEAD` at `1a4737e0747becfe466a99bf25782453ce06731f` |
| Starting worktree | clean: no staged changes, no unstaged changes, no untracked files |
| Remote of that commit | `origin/cursor/memory-workflow-alignment-9cb3` already pointed at the same commit |
| Backup branch | `backup/pre-signal-memory-20261120-2120` |
| Work branch | `work/signal-memory-simplification` |
| Checkpoint commit | `1a4737e0747becfe466a99bf25782453ce06731f` |
| Push | regular push of both new branches. Neither name existed on the remote, so nothing was overwritten |
| Restore | `backup/pre-signal-memory-20261120-2120` stays at that commit. No commit is added to the backup branch |

`cursor/memory-workflow-alignment-9cb3`, `cursor/memory-signal-v1-56d5`, and `codex/feishu-shared-source-acceptance` were not updated.

The parent of this audit commit, and the backup branch, remain the original tree. To restore the product tree: `git checkout backup/pre-signal-memory-20261120-2120`.

## B. Pre-change audit

Status values: DONE, PARTIAL, STUB, MISSING, REDUNDANT, UNVERIFIED.

### What `1a4737e` actually does

Grok's earlier commit `4efd804` is an ancestor. The behavior below is the tree at `1a4737e`, read from the functions, not from that commit message.

- One current Search Memory row per candidate. The first publish calls `FeishuGateway.append_memory_row`. Later publishes patch that same `record_id`, set `version` to `int(previous) + 1`, and set `supersedes_version` on that same row (`SharedMemoryService._publish_serial`).
- More than one `published` row in a domain is rejected. Legacy `retained` rows are ignored when exactly one `published` row exists. A domain that has only `retained` rows is rejected, not treated as empty (`_domain_rows`).
- The memory body is structured text columns (`keywords`, `role_directions`, `exclusions`, `notes`, `reason`, `content_digest`). It is not a Markdown document.
- Dream writes a `dream_batch` JSON object into the existing Human Signals `source_context` cell. There is no `dream_run_id` column in the mapped fields.
- A signal is marked `learned` only after `_confirmed_row` re-reads the memory row and the content hash and version match. Dream passes `advance_signal=False` into publish, then `_mark_batch_learned`.
- `pin_fetch_memory` copies the applied keyword snapshot into the returned `FetchMemoryPin`. `last_consumed_version` is set equal to `memory_version` on that object. Nothing writes it back to the Base. `continue_fetch` returns the caller-supplied pin and does not re-read the memory row, because an in-place update would already have replaced the previous snapshot.
- The 10-business-day window is a caller-supplied `[window_start, cutoff]` plus `window_business_days: 10` and an IANA timezone. The code checks ordering and that the timezone exists. It does not count business days or holidays.

### 1. Signal capture and event-source recognition

| | |
|---|---|
| Status | PARTIAL for a local fixture parser. MISSING as a production capture path |
| Files | `src/jobagent/memory/signal.py` (`SignalInbox.receive`, `_classify`, `_learnable`); `src/jobagent/memory/workflow_signal.py` (`parse_workflow_signal`); `src/jobagent/cli/memory.py` (`signal-receive`, `workflow-page`); `src/jobagent/schemas/shared_memory.py` (`DISABLED_WORKFLOWS`) |
| Responsibility | Two different readers. `SignalInbox` parses one local `drive.file.bitable_record_changed_v1` JSON fixture. `parse_workflow_signal` reads a Human Signals row that some other writer is assumed to have appended |
| What it does | The fixture parser keeps a human edit of one watched field when operator, before, and after are all present and different. Bot and unknown operators do not become signals. The workflow parser checks the row against three hard-coded disabled workflow definitions and the jobs table id. It does not subscribe to Feishu and does not create the row |
| Upstream | `jobagent memory signal-receive` (fixture file). `jobagent memory workflow-page` (Feishu query). No other `src/` caller |
| Downstream | Fixture output stays in process / optional local receipt file. Workflow page returns rows still in `pending_history_enrichment`. Neither path writes Memory |
| Problem | Production capture is not in this repo. `DisabledWorkflow.enabled` is fixed to `False`. There is no command that creates a Human Signals row. `FeishuGateway.append_memory_row` refuses every table except `search_memory` and `greeting_memory`. The native event parser is explicitly not a connected subscription |
| Recommendation | keep both parsers as they are. Do not enable the three workflows. Do not add a webhook, a socket, or a poller in the next change |
| Evidence | `signal.py` module docstring; `DISABLED_WORKFLOWS` in `schemas/shared_memory.py`; `tests/memory/test_memory_signal.py`; `tests/bridge/test_shared_memory_alignment.py::test_production_tables_and_workflows_stay_disabled` |

### 2. Human Signals write and read

| | |
|---|---|
| Status | DONE as a reader and as a patcher of enrichment / `learning_status` / `source_context`. MISSING as a row creator |
| Files | `SharedMemoryService.page_workflow_signals`, `enrich_signal`, `_stamp_batch`, `_set_learning_status`; `FeishuGateway.query`, `get`, `patch`; `workflow_signal.py` |
| Mapped fields | 15 names in `HUMAN_SIGNAL_FIELDS`: `source_table`, `source_record_id`, `job_title`, `field_name`, `field_id`, `signal_type`, `memory_domain`, `learning_status`, `signal_id`, `source_context`, `operator_id`, `operator_name`, `changed_at`, `before_value`, `after_value` |
| Live width | `_validate_human_signals` requires the live table to have exactly 19 fields and the private config to map exactly those 15 names. The other 4 live columns are not named in code. Whether any of them is `event_id`, `memory_version`, or `dream_run_id` is **UNVERIFIED**. Do not guess their field ids |
| Status set | `pending_history_enrichment`, `pending_dream`, `learned`, `unknown` |
| What a workflow row looks like on arrival | The fixture `tests/bridge/fixtures/workflow_human_signal.json` has null `signal_id`, `source_context`, operator, time, and before/after. `learning_status` is `pending_history_enrichment`. `enrich_signal` does not write `signal_id` |
| Upstream | Host calls `memory workflow-page` / `enrich-signal` / dream commands. No in-repo scheduler calls them |
| Downstream | Enrichment patch. Dream stamp in `source_context`. Later `learning_status=learned` |
| Problem | The table is a queue the repo can update and cannot fill. `signal_id` is never assigned by enrichment. Record id is the id Dream actually uses |
| Recommendation | keep the 15-field mapping and the four statuses. Do not add columns in this plan |
| Evidence | `HUMAN_SIGNAL_FIELD_COUNT = 19` versus `HUMAN_SIGNAL_FIELDS`; `enrich_signal`; `_enrichment_fields` |

### 3. History Match / historical attribution

| | |
|---|---|
| Status | DONE for a single readable edit. REDUNDANT as a strategy once a field has been edited twice, which is the normal case |
| Files | `src/jobagent/memory/history_match.py` (`parse_history_page`, `classify_history_operator`, `match_history`); `FeishuGateway.record_history`; `SharedMemoryService.enrich_signal` |
| What it does | Reads `base +record-history-list` for one jobs record until the page budget ends or `has_more` is false. If the watched `field_id` appears in exactly one history item, the before/after are strings, the activity is `update`, revision and time exist, and the operator id is in exactly one of the human or bot sets, the diff is `matched_human` or `matched_bot`. Any other shape is `unknown` and `grants_learning` is false |
| Upstream | `memory enrich-signal`, and `feishu record-history` (read only, does not advance status) |
| Downstream | On `matched_human`, enrichment sets `pending_dream` and copies before/after, time, and operator. Every other reason sets `unknown`. A failed history read or an unverified patch leaves `pending_history_enrichment` |
| Problem | `match_history` returns `ambiguous_field_change` when the same field appears twice in the history of that record. It discards both values. The second real correction of 匹配档位 makes that record unlearnable by this path. The workflow row does not carry an event id that would select one of the two edits. This is asserted on purpose |
| Recommendation | simplify the call, not the fail-closed matcher. If a Human Signals row already has before, after, time, and a human operator id, do not call history. Keep `match_history` for rows that are still empty, and keep the ambiguous result. Do not add reason codes |
| Evidence | `history_match.py` `len(found) != 1`; `tests/bridge/test_history_match.py::test_two_sequential_edits_on_one_field_remain_ambiguous_without_event_correlation`; `test_shared_memory_alignment.py::test_duplicate_history_or_display_name_stays_unknown` |

### 4. MCP Gateway / Feishu CLI transport

| | |
|---|---|
| Status | DONE as two separate transports. The premise that MCP is the front door to the Feishu CLI is not true in this repo |
| Feishu path | `jobagent feishu` → `cli/feishu.py::gateway` → `LarkCliTransport.call` → `subprocess` of the configured executable with `--as`, `--format json`, no shell. `FeishuGateway` then does `+field-list`, `+record-list`, `+record-get`, `+record-batch-update`, `+record-history-list`, and `+record-batch-create` (memory tables only) |
| MCP search path | `jobagent mcp` → `connectors/mcp_gateway.py::McpReadGateway`. Operations are search and view. Unknown after dispatch is not replayed |
| MCP stdio server | `src/jobagent/bridge/mcp_server.py` exposes console/status/mailbox tools. It does not import `FeishuGateway` |
| Upstream of Feishu | Host process runs the CLI. This repo does not contain a tunnel or an MCP tool whose implementation calls `lark-cli` |
| Downstream | Shared memory, worker shared read (`cli/worker.py::_GatewaySharedReader.current` is `get` only), and a host-built `feishu patch` JSON |
| Problem | A host can wrap the CLI outside the repo. That wrapping is **UNVERIFIED** here. Adding an MCP Feishu proxy would be a new interface and is not required for the CLI that already exists |
| Recommendation | keep `LarkCliTransport` and `McpReadGateway` unchanged. Do not route memory through `mcp batch` |
| Evidence | `mcp-runtime.md` ("可执行操作只有 search 与 view"); `feishu_gateway.py::LarkCliTransport.call`; `mcp_server.py` tool list |

### 5. Actor identity and write-source recognition

| | |
|---|---|
| Status | PARTIAL. Human versus bot is implemented for history and for the fixture parser. Generation agent versus execution agent versus initial bot is not |
| Files | `OperatorDirectory` and `classify_history_operator` / `SignalInbox._classify`; `FeishuConfig.identity` (`user` or `bot`, one value for the whole CLI process); `FeishuPatch.role` (`generation`, `execution`, `memory`) |
| What it does | An operator id in both sets, in neither set, or missing, is `unknown`. Display name alone is `unknown`. `FeishuPatch.role` only checks the config writable list. The only production constructor of `FeishuPatch` in `src/` is `SharedMemoryService`, and it always passes `role="memory"`. `generation` and `execution` are available to a host that calls `jobagent feishu patch` with a JSON body. The role is not written onto the jobs row or the signal row |
| Initial bot | No symbol, no writer of the jobs table named initial bot. `WorkerGateway.ingest` writes the local database, not Bitable |
| Upstream | Private operator JSON on `enrich-signal` and both dream commands. Empty directory is rejected by the dream CLI tests because an empty directory would classify every id as unknown |
| Problem | If GPT and Muse both use `identity=user` and the human's open_id, record history shows the human for agent writes. The call context that distinguishes them (`FeishuPatch.role`) is discarded after the process exits. There is no persisted source mark to recover it the next day. A new identity service is not required to explain this. A stored mark is required only if those agents share the human id. Whether the private configs already put both agents in `bot_open_ids` is **UNVERIFIED** (private config is not in the repo) |
| Recommendation | change nothing until that config fact is known. Do not add a multi-user directory. If the agents are already bot ids, history already excludes them. If they share the human id, the smallest mark is a value written at `feishu patch` time into an existing text cell whose field id the user reads off the live base. This plan does not choose a field id |
| Evidence | `history_match.py::classify_history_operator`; `schemas/feishu.py` `FeishuRole`; grep of `FeishuPatch(` under `src/` hits only `shared_memory.py` |

### 6. Dream / Memory aggregation

| | |
|---|---|
| Status | DONE as a freeze-and-fold service. MISSING as a model call and as a scheduler. The model step is intentionally outside the repo |
| Files | `SharedMemoryService.start_dream_batch`, `_resume_batch`, `complete_dream_batch`, `_stamp_batch`, `_mark_batch_learned`; `memory/snapshot.py::fold_search_snapshot`; `cli/memory.py` `dream-batch-start`, `dream-batch-complete`; `skills/job-hunting/references/memory-dream.md` |
| What it does | Start lists `pending_dream` rows, keeps `matching_correction` / `search_match` rows whose operator is in the human set and whose `changed_at` is inside the caller window, sorts them, cuts at `batch_size`, and writes the same checkpoint JSON onto each chosen row's `source_context`. Greeting and workflow rows are left untouched. Complete requires one caller-supplied `SignalPreferenceDelta` per frozen id, folds those deltas onto the current search row, and publishes one full snapshot. A fold equal to the current lists marks the signals learned and does not bump `version`. A fold that would erase a non-empty baseline down to empty lists is rejected. No baseline and an empty fold creates no row |
| Upstream | Host process. Nothing in `src/` calls `start_dream_batch` except the CLI. Patrol source is asserted not to contain that name (`test_dream_batch.py`) |
| Downstream | One search_memory row. Signal `learning_status`. No send, no fetch, no jobs-table write |
| 10-day window | Filters which pending rows may enter the batch. Learned rows are not selected again. Rows outside the window stay `pending_dream` and are not deleted. Existing keywords on the memory row are the baseline `fold_search_snapshot` starts from. The window does not delete a keyword that failed to recur |
| Concrete gap | The code does not interpret "still pending, but older than the latest 10 business days". A host that always passes the latest window will never learn a `pending_dream` row whose `changed_at` has aged out. The reference tells the host to do exactly that. See section G |
| Recommendation | keep start and complete. The split is the slot where GPT reads the frozen ids and returns deltas. Keep the `source_context` checkpoint. Do not add a stage enum, a second scheduler, or a model client |
| Evidence | `_start_dream_batch`, `_human_ready`, `fold_search_snapshot`; `test_signals_outside_the_rolling_ten_workday_window_stay_pending`; `test_no_net_change_marks_signals_learned_without_publishing_a_new_version`; `test_search_dream_excludes_greeting_and_workflow_signals` |

### 7. Memory Markdown read / write / publish

| | |
|---|---|
| Status | The Bitable loop the premise describes is PARTIAL and is not Markdown. A different local Markdown store is DONE and is not this loop |
| Bitable memory | `memory/publication.py` (`memory_row_fields`, `decode_memory_row`, `assert_publishable`); `SharedMemoryService.publish_memory` / `_publish_serial` / `_confirmed_row` / `_restore_previous_snapshot`. Kinds `search` and `matching` share table `search_memory` (`tbldfiISJ1zdNByn`). Kind `greeting` uses `greeting_memory` (`tblf1Q2iSfUPyzph`). Kind `workflow` is refused. Publish reads the jobs row `candidate_id` through the private field map and refuses a mismatch |
| Write-then-read | After create or patch, `_confirmed_row` loads the domain again. The row counts as landed only when there is one published row, the record id matches, `body_digest` equals the digest of the body, and `version` equals the version just written. Signals are not moved to `learned` when that check fails |
| Torn write | `_restore_previous_snapshot` runs only when confirmation fails. It writes the previous values back only if every observed field is either the previous value or the attempted value. Otherwise it reports restoration false and does not overwrite a conflicting edit |
| Local Markdown | `bridge/preference_memory.py::MarkdownPreferenceStore` reads and writes a private `preference-memory.md`. `jobs search-plan --memory-settings` and `cli/greetings.py` call `refresh_preference_memory`. `memory status/compile/context` (`memory/service.py`) snapshots private files. None of these read or write the Bitable memory tables |
| Local JSON memory | `memory signal-compile` plus `memory apply-search` publish a `PublishedMemoryFile`. `jobs search-plan --search-memory` reads that file. It does not call `fetch-pin` |
| Problem | Three stores can all be described as memory. Only the Bitable search row is what Dream writes and `fetch-pin` reads. It is column-shaped JSON text, not a Markdown cell and not a file named Memory.md. Greeting Bitable rows have a publisher (`publish-version`) and no Dream or Fetch reader |
| Recommendation | keep the one-row in-place search publish. Do not add a Markdown column. Do not delete `MarkdownPreferenceStore` in this simplification: greeting generation and `search-plan --memory-settings` still use it. Do not point Fetch at that file |
| Evidence | `SEARCH_MEMORY_FIELDS`; `_publish_serial` lines that set `version = str(int(current.version) + 1)` and patch `current.record_id`; `test_in_place_update_keeps_one_record_and_bumps_version`; `preference_memory.py::_document` |

### 8. Muse Fetch memory consumption

| | |
|---|---|
| Status | PARTIAL. The pin command is DONE. The Fetch implementation does not call it |
| Files | `SharedMemoryService.pin_fetch_memory`, `continue_fetch`; `memory/search_round.py::plan_search_round`; `jobs/search_memory_apply.py::apply_search_memory`; CLI `fetch-pin`, `fetch-continue`, `search-round` |
| What the pin does | Reads the one published `kind=search` row, checks the content hash by decoding the row, and returns keywords, directions, exclusions, version, record id, and hash. Hard constraints, query count, and top-per-query are copied from the caller and not taken from memory. `grants_fetch` and `grants_send` are fixed false. No memory returns the caller config with `applied=false`, and a later publish does not change a pin that started with no memory |
| What Fetch does | `jobs fetch` / `jobs fetch-jd` load listings through connectors. `mcp batch` runs search/view. Neither imports `SharedMemoryService`. A host can take `fetch-pin` JSON and pass keywords into `jobs search-plan`, but no code does that |
| Recommendation | keep the pin. Do not modify Fetch, search, or match code. The host, not a new consumer inside `jobs.py`, should apply the pin's keyword list with the existing search-plan input |
| Evidence | `cli/jobs.py` `fetch` and `search-plan`; `connectors/mcp_gateway.py`; `test_muse_keeps_a_pinned_version_and_a_later_fetch_reads_the_latest` (service-level, not a live Muse run) |

### 9. Scheduled tasks and external entries

| | |
|---|---|
| Status | MISSING inside the repo, on purpose for the 03:00 job. The CLI entry the external job would call is DONE |
| Entries that exist | `jobagent memory dream-batch-start`, `dream-batch-complete`, `fetch-pin`, `fetch-continue`, `workflow-page`, `enrich-signal`, `publish-version`, `search-round`; `jobagent feishu schema/query/get/record-history/patch` |
| Entries that do not exist | A cron, a 03:00 registration, a Feishu bot push, a webhook server, a resident Dream agent, a memory poller. `hosts/personal-ai/tasks.md` is host instructions. The repo does not execute those tasks |
| Recommendation | keep the CLI as the tunnel surface. Do not move ChatGPT's scheduler into the repo |
| Evidence | `cli/memory.py` command functions; `test_dream_batch.py` assertion that patrol source has no `start_dream_batch`; `hosts/personal-ai/memory.md` says the host loads `memory-dream.md` |

### 10. Tests, config, and docs

| | |
|---|---|
| Status | DONE as synthetic-fixture coverage of the service. UNVERIFIED against the live base. This audit did not execute pytest |
| Tests | `tests/bridge/test_dream_batch.py`, `tests/bridge/test_shared_memory_alignment.py`, `tests/bridge/test_history_match.py`, `tests/bridge/test_feishu_gateway.py`, `tests/memory/test_memory_signal.py`, `tests/cli/test_feishu.py` |
| Config | `FeishuConfig` is private and not committed. `PRODUCTION_TABLE_IDS` names jobs `tbl0m4LpWgeGuZEd`, human signals `tbldP0Buy3hrwOmT`, search memory `tbldfiISJ1zdNByn`, greeting memory `tblf1Q2iSfUPyzph`. Watched field ids in `DISABLED_WORKFLOWS`: 匹配档位 `flddtn4pvI`, 招呼语 `fld0jsS3ei`, 处理进度 `fldarFiHsF`. Jobs `candidate_id` field id is not in the repo; publish fails closed when the private map lacks it |
| Docs that describe this loop | `skills/job-hunting/references/memory-dream.md`, `skills/job-hunting/references/feishu-shared-source.md`, `skills/job-hunting/references/capability-catalog.md`, `docs/reviews/2026-11-20-memory-dream-fetch-followup.md` |
| Docs that describe a different loop | `hosts/personal-ai/memory.md` (local L1/L2 and preference markdown), `docs/grok-handoff-acceptance.md` (fixture `signal-receive` path) |
| Recommendation | keep the fixture tests. After any later code change, extend `test_history_match.py` and `test_shared_memory_alignment.py` rather than replacing them with a live-host story |
| This run | `python3` 3.12.3 is present. `pytest` is not installed. No test command was run. GitHub Actions billing failures are not a code result |

### Facility judgment

| Facility | Judgment | Action | If deleted |
|---|---|---|---|
| Multi-layer operator attribution | can-be-simplified later, not now | keep `OperatorDirectory` human/bot. Do not add agents to it | Deleting the directory makes every operator unknown and stops learning |
| History match | can-be-simplified | keep the matcher; stop calling it for an already complete human row | Deleting it leaves empty workflow rows at `pending_history_enrichment` forever |
| Four signal statuses | necessary | keep | Collapsing `unknown` into pending would retry bot rows forever |
| Dream start/complete plus `source_context` checkpoint | necessary | keep | One call cannot surround the external GPT step. Without the checkpoint a crash mid-stamp loses the frozen id set |
| Multiple retained/published rows | redundant as a writer; the reader guard is necessary | keep the guard. The writer already only emits `published` | Deleting the guard makes a leftover retained-only domain look like "no memory" and the next publish creates a second lineage |
| Version on the one row, plus caller-held fetch pin | necessary | keep. Do not persist `last_consumed_version` | Without the pin, an in-place update during a round changes the keywords under an in-flight Fetch. Without the version, confirmation cannot tell a new body from a replay |
| `publication_status` state machine | already two values, one of which is legacy | keep the read guard. Do not add states | Same as the retained-row row above |
| Process lock `_PUBLISH_GUARD` | not a distributed lock. Low value for CLI | keep the existing in-process set. Do not add a cross-process lock | Two threads in one process could interleave. Two CLI processes already can, because each process has its own set. A distributed lock would be new infrastructure for a single-operator daily job |
| Layered retries | the dangerous kind is absent | keep caller-driven idempotent replay (`body_digest` match, batch stamp equality, `_published_covering`). Do not add a retry loop | The gateway already returns `unknown` with `do_not_repeat` |
| Self-healing polling | does not exist | do not add | — |
| Torn-write restore | necessary, one shot | keep `_restore_previous_snapshot` | A partial field update fails `decode_memory_row` on digest mismatch and the only search row becomes unreadable. Fetch must not drop the previous preference to get past that |
| Content hash and version | not redundant | keep both. Hash is the body. Version is the generation. Feishu `content_digest` is a different pre-write token | Dropping the hash lets a wrong body be marked learned. Dropping the version lets a replay look like a new publish |
| Second and third memory stores | separate products | do not merge and do not delete them in this pass | Deleting `MarkdownPreferenceStore` changes greeting generation and `search-plan --memory-settings` |

## C. Proposed modification list

No file below is modified by this audit commit except this document.

The safe code slice is one behavior change: `enrich_signal` trusts a row that is already a complete human diff and does not call history. Empty rows keep today's history path. That slice does not create Human Signal rows, does not enable workflows, and does not connect Fetch.

### `src/jobagent/bridge/shared_memory.py`

| | |
|---|---|
| Status | DONE |
| Responsibility | Queue read, history enrichment, dream freeze, in-place publish, fetch pin |
| Delete | Nothing in the first slice. Do not delete `_restore_previous_snapshot`, `_confirmed_row`, or the single-published-row check |
| Keep | `start_dream_batch`, `complete_dream_batch`, `_publish_serial` in-place update, learned-only-after-confirm, greeting exclusion, window filter, candidate check through the jobs row |
| Change | In `enrich_signal`, before `gateway.record_history`: if `before_value`, `after_value`, `changed_at`, and `operator_id` are already non-empty, `before != after`, and `_human_ready` would accept the row apart from status, patch `learning_status` to `pending_dream` and return. If the operator is in the bot set, patch `unknown`. If the id is in neither set, leave the row and return `unknown` without a history call. If any of those cells is empty, call history exactly as today |
| New files / fields | None |
| Why | A second edit of the same jobs field makes history ambiguous. A row that already carries the one edit does not need history. Today's workflow fixture has those cells empty, so its behavior stays on the history path |
| After | Complete rows advance without `ambiguous_field_change`. Incomplete rows still advance only on a unique human history diff |
| Tests | Extend `tests/bridge/test_shared_memory_alignment.py`: complete human row skips history; bot id on the row becomes `unknown` and does not call history; empty row still calls history; two history edits still do not advance |

### `src/jobagent/memory/history_match.py`

| | |
|---|---|
| Status | DONE |
| Responsibility | Fail-closed unique field diff |
| Delete | No function. Do not delete `ambiguous_field_change` |
| Keep | `parse_history_page`, `classify_history_operator`, `match_history` |
| Change | None in the first slice. Callers change, this file does not |
| New files / fields | None |
| Why | The matcher is the right behavior for an empty row. The bug is using it as the only attribution after the field has a real history |
| After | Unchanged function. Fewer calls once rows arrive complete |
| Tests | Existing `tests/bridge/test_history_match.py` stays as the contract for the empty-row path |

### `src/jobagent/cli/memory.py`

| | |
|---|---|
| Status | DONE |
| Responsibility | CLI surface for the service |
| Delete | No command in the first slice. Do not delete `signal-receive` or `signal-compile`; `jobs search-plan --search-memory` still reads their file output |
| Keep | `dream-batch-start`, `dream-batch-complete`, `fetch-pin`, `enrich-signal`, the required `--operators` file |
| Change | None until the enrich change above needs a new flag. It does not |
| New files / fields | None. Do not add a cron command |
| Why | GPT's external 03:00 task should call the commands that already exist |
| After | Same CLI |
| Tests | `test_dream_cli_requires_an_explicit_operator_directory` |

### Files that must not change in that slice

| Path | Why it stays |
|---|---|
| `src/jobagent/bridge/feishu_gateway.py` | CLI transport, role whitelist, approval refusal, unknown write is not retried, create limited to the two memory tables |
| `src/jobagent/connectors/mcp_gateway.py`, `src/jobagent/bridge/mcp_server.py`, `src/jobagent/cli/mcp_calls.py` | Search/view and console MCP. Not the Feishu path |
| `src/jobagent/cli/jobs.py` `fetch`, `fetch-jd`, `search-plan`; `src/jobagent/jobs/matching.py`; `src/jobagent/jobs/search_plan.py` | Fetch, match, and search planning |
| `src/jobagent/bridge/worker.py`, `src/jobagent/jobs/shared_send_gate.py` | Approval and send control. Worker reads Feishu; it does not patch it |
| `src/jobagent/bridge/preference_memory.py`, `src/jobagent/outreach/preference_memory.py`, `src/jobagent/cli/greetings.py` | Local greeting preference file. A different store |
| `src/jobagent/memory/signal.py`, `src/jobagent/memory/signal_compile.py` | Fixture and local JSON path. Not the Bitable producer |
| `src/jobagent/memory/publication.py`, `src/jobagent/memory/snapshot.py`, `src/jobagent/memory/search_round.py`, `src/jobagent/jobs/search_memory_apply.py` | One-row body, fold, and keyword apply. Already match the in-place model |
| `src/jobagent/schemas/shared_memory.py` | No new status, no new field, workflows stay `enabled=False` |
| Jobs / events pipeline modules | Business state machine. Dream does not write it |

### Docs to touch only in the same later change, not in this audit

| Path | Change |
|---|---|
| `skills/job-hunting/references/memory-dream.md` | State that the memory body is the one search row's keyword lists, not a Markdown file; the host calls the existing dream CLI; Fetch is not invoked by the service |
| `skills/job-hunting/references/capability-catalog.md` | Only if a command's contract text changes. The enrich shortcut is still `memory enrich-signal` |
| `skills/job-hunting/references/feishu-shared-source.md` | One sentence: history is the fill-in for an empty signal row, not the attribution of every later edit |

`tests/test_capability_status.py` must stay consistent with the catalog. No new command is proposed, so that test should not need a new row.

## D. Proposed deletion list

Proposed only. Nothing here was deleted.

| Item | Why it is not the next deletion |
|---|---|
| `SignalInbox`, `signal-receive`, `SignalCompiler`, `signal-compile`, `apply-search` | Local fixture path. `search-plan --search-memory` still consumes the file. Deleting it changes a working local tool. Leave it unwired to Bitable |
| `MarkdownPreferenceStore` and `memory compile` | Greeting and private-file context use them. They are not a second copy of the Dream row unless a host points Fetch at both. Do not delete |
| `_PUBLISH_GUARD` | In-process only. Deleting it does not fix two CLI processes and it weakens the in-process tests. Do not replace it with a distributed lock |
| `publication_status=retained` handling | Dead as a writer, live as a guard against old rows. Live presence of such rows is **UNVERIFIED**. Keep the guard |
| `match_history` | Still the only way an empty workflow row can become `pending_dream` |
| Four `LearningStatus` values | Each one is a real queue state. `unknown` means "do not learn", not "try again" |
| Dream checkpoint JSON | It is the frozen id list between two CLI calls. Not a second memory |
| Extra `event_id` / `memory_version` / `dream_run_id` columns | Not mapped. Do not add them. `signal_record_id`, memory `version`, and `source_context.dream_batch.batch_id` already carry those roles |
| A Memory.md cell or file as the Dream record | Would be a second body beside `keywords` / `role_directions` / `exclusions`. Fetch applies those lists, not Markdown |
| New Human Signals table, operator service, webhook, poller, scheduler, Feishu push | Not present. Do not add them |

## E. Current chain and target chain

### Current chain, with status

```text
Human UI edit of 匹配档位 / 招呼语 / 处理进度
    status: MISSING in this repo
    the three workflows are constants with enabled=False
    no src/ function inserts a Human Signals row

Initial bot job-table write
    status: MISSING as a Bitable writer
    WorkerGateway.ingest writes local sqlite only

GPT or Muse job-table write
    status: PARTIAL
    host may run `jobagent feishu patch` with role generation or execution
    that role is not stored
    SharedMemoryService never writes the jobs table

        │
        ▼
MCP tools
    status: DONE for search/view only (`McpReadGateway`)
    status: MISSING as a Feishu transport
    `mcp_server.py` does not call the CLI

        │  (not connected)
        ▼
Feishu CLI
    status: DONE
    LarkCliTransport → official executable, argv, no shell
    commands: jobagent feishu schema|query|get|record-history|patch
    memory commands use the same gateway

        │
        ▼
Bitable
    status: adapter DONE, live schema UNVERIFIED
    jobs tbl0m4LpWgeGuZEd
    human signals tbldP0Buy3hrwOmT
    search memory tbldfiISJ1zdNByn
    greeting memory tblf1Q2iSfUPyzph

        │
        ▼
Signal
    status: PARTIAL
    read/patch DONE (`workflow-page`, `enrich-signal`)
    create MISSING
    history match DONE and fails closed on the second edit of a field

        │
        ▼
Memory
    status: DONE for one in-place search row
    Dream model call MISSING here (host supplies SignalPreferenceDelta)
    greeting table has no Dream and no Fetch reader
    local preference-memory.md is a separate store

        │
        ▼
Fetch
    status: pin command DONE
    jobs fetch / mcp batch do not call the pin
    consumption of the Dream row by Muse is MISSING
```

### Target chain, without new infrastructure

```text
Human edit
    still needs a producer decision (section G)
    this plan does not enable workflows and does not add a poller

Agent write through the existing CLI
    `jobagent feishu patch` role stays the call-context distinction
    no new identity service
    persist a source mark only after the user names an existing field id

GPT at 03:00, outside this repo
    jobagent memory workflow-page
    jobagent memory enrich-signal
    jobagent memory dream-batch-start --operators <private>
    GPT reads the frozen signal ids and the current search row
    jobagent memory dream-batch-complete
    service folds deltas into the same search record, version + 1,
    re-reads content_digest, then marks those signals learned

Next Muse Fetch, host-side, Fetch code unchanged
    jobagent memory fetch-pin
    host passes the returned keywords into the existing search-plan inputs
    jobagent memory fetch-continue with the same pin JSON if the round is still open
    do not also inject preference-memory.md as a second search policy
```

Greeting stays on `greeting_memory` and on the local preference file. This plan does not merge those domains. Workflow outcome signals stay out of search keywords.

## F. Tests actually run

None.

`python3` is 3.12.3. `pytest` is not installed in this VM. The suite was not run, and no count from another machine is repeated here as if it were this run. GitHub Actions on the repo failing before a runner is assigned is a billing lock, not a pytest result.

## G. Questions that block the Human Signal → Dream → Memory → Fetch loop

1. **Who inserts Human Signals rows while the three workflows stay disabled?** This repo does not. `signal-receive` does not write Bitable. Without a producer, Dream's `pending_dream` query is empty no matter how simple enrich becomes. Acceptable answers are: the rows are already written by something outside this repo whose contract matches `workflow_human_signal.json`, or the user later authorizes a create on the existing Human Signals table. A webhook, an enabled workflow, and a new poller are not proposed.

2. **Do GPT and Muse use a bot open_id, or the human's open_id?** Private Feishu config is not in the repo. If both agents are already in `bot_open_ids` / `bot_union_ids`, history already refuses them and no source column is required. If they share the human id, say so and name the existing text field that should store `initial_bot` / `human` / `generation_agent` / `execution_agent`. This plan will not invent the field id. `FeishuPatch.role` already distinguishes generation, execution, and memory for the life of one CLI call, and then forgets it.

3. **Is jobs `candidate_id` mapped in the private config, and is that live field type `text`?** Publish and Dream refuse to run when it is missing or not text. The field id is **UNVERIFIED**.

4. **What are the 4 live Human Signals columns that are not in the 15-name map?** The code requires 19 live fields. It does not name the extra 4. If one of them is already a per-edit event id, mapping it would let history pick one edit. That mapping needs the user to read the live schema. It is not assumed.

5. **Missed window.** A `pending_dream` row whose `changed_at` falls outside the host's latest 10-business-day window stays pending forever under the current filter. It is not deleted, and it is not folded. Confirm which behavior is wanted: leave it out until a window covers that timestamp, or let a later batch take still-pending rows older than 10 business days without removing keywords from Memory. The code implements the first. Memory keywords are not trimmed either way.

These are not blockers and are not proposed work: a second CLI process racing one daily Dream, a lost fetch-pin JSON (the next `fetch-pin` reads the current row), Feishu record history pagination past the existing page budget, and persisting `last_consumed_version` on the Base.

## H. Boundaries

| Boundary | Decision |
|---|---|
| Deletion | No product file deleted. Do not delete history match, the four statuses, the dream checkpoint, the one-row version, the content-hash confirmation, the torn-write restore, or the local preference-memory store |
| Keep | Event-row dedup by record id, write then re-read before `learned`, fail the read instead of an empty success, bot/unknown is not a preference, greeting and workflow stay out of search Dream, workflows stay disabled, Fetch/match/send code stays as it is |
| New capability | None in the proposed slice. No table, no column, no MCP method, no scheduler, no subscription |
| Bitable schema | No change proposed. Extra live columns stay unmapped until the user names them |
| MCP | No change. Memory stays on `jobagent memory` / `jobagent feishu` |
| Fetch and generation | Not affected by the enrich shortcut. They start using the Dream row only when the host passes `fetch-pin` output into the existing search inputs |

## Premise check

| Premise | Verdict from this tree |
|---|---|
| Private single-operator skill, not multi-user SaaS | Holds. `OperatorDirectory` is one human set and one bot set. No tenant key |
| Only a human edit may become a preference | Holds in the matcher and in `_human_ready`. It does not hold for a shared user identity, because the role is not stored |
| Bitable is the only business state machine for this loop | Holds for Dream: one search row, signals updated in place, checkpoint in `source_context`. It does not hold for the whole product: local sqlite, `preference-memory.md`, and `signal-compile` JSON files are separate and still used by greeting and search-plan |
| Memory.md is a Markdown cell in Bitable, one valid body, read by the next Fetch | The one-row and one-body part holds. The Markdown part does not. The body is structured columns. Fetch does not read them until the host calls `fetch-pin` |
| Dream is a daily external GPT call through the existing CLI | The CLI exists. The schedule does not, and should not be added here. The service does not call a model |
| 10-day window selects recent signals and does not expire Memory | Holds for keywords. The window is not computed in code. Aged-out pending rows are the open question in G.5 |
| In-place single record, dream batch JSON in `source_context`, pin is the snapshot at read time, `last_consumed_version` is not on the Base | Holds at `1a4737e` |
