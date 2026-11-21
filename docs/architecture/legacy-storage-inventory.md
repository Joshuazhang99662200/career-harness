# 旧存储盘点：SQLite 表、Repository 与本地文件

基线：PR #36 head `f3eb022`。方法：解析 `src/jobagent/storage/migrations/*.sql` 的 `CREATE TABLE`，再对 `src/` 全部 `.py` 检索 `FROM / JOIN / INTO / UPDATE / TABLE <name>`。数据库默认路径 `.jobagent/jobagent.sqlite3`（各 CLI 的 `--database` 默认值），由 `storage/database.py` 统一打开与迁移。

处理取值：**keep**（保留，非业务权威）/ **migrate**（数据与能力迁入 Bitable 域后退役）/ **retire**（替代路径验收后删除，无需迁移数据或仅一次性导出）/ **confirm**（需本人裁定，见[审计 §5](audit-current-state.md#5-需要本人裁定的冲突confirm)）。

## 1. 按业务域分组的 123 张表

| 域 | Migration | 表 | 主要读写方 | 目标归属 | 处理 |
|---|---|---|---|---|---|
| Candidate Core / Evidence | 0001 | `candidate_profiles`, `evidence_items`, `resume_ingestions`, `interview_events` | `storage/candidate_repository.py`；读：`bridge/greeting_context.py`、`bridge/preference_memory.py`、`console/outreach.py`、`storage/feedback_repository.py`、`bridge/memory_sources.py` | Materials | confirm（硬性边界 `CandidateEvidenceService.confirm`） |
| Profile 飞轮 / 评测 | 0010, 0013 | `harness_versions`, `profile_snapshots`, `profile_versions`, `profile_proposals`, `profile_asks`, `profile_approvals`, `profile_applications` | `storage/evals_repository.py` | Materials（Profile 正文）或 Greeting Memory（表达策略） | confirm |
| Jobs 主数据 | 0002, 0010, 0012, 0029 | `normalized_jobs`, `job_provenance`, `job_requirements`, `hard_filter_results`, `job_matches`, `job_search_hits`, `job_searches`, `job_observations` | `storage/job_repository.py`；读：`bridge/status.py`、`bridge/worker.py`、`bridge/panel_decisions.py`、`bridge/greeting_context.py`、`storage/pipeline_metrics.py` | Jobs | migrate |
| JD 知识 | 0015, 0016 | `jd_snapshots`, `jd_discoveries`, `jd_feature_sets`, `jd_lexicon_versions`, `jd_query_plans` | `storage/jd_snapshot_repository.py`、`storage/host_reports.py`、`storage/intake_strategy.py` | JD 正文与版本 → Jobs；词表版本是工具配置 | migrate（快照）/ confirm（词表） |
| 投递 | 0003 | `application_audits` | `storage/application_repository.py` | Jobs 执行结果 | confirm（无对应域字段） |
| Outreach 审批与审计 | 0004, 0009, 0011 | `outreach_batches`, `outreach_asks`, `outreach_approvals`, `outreach_audits`, `outreach_leases`, `outreach_withdrawals`, `outreach_audits_next` | `storage/outreach_repository.py`；读：`bridge/status.py`、`console/outreach.py`、`bridge/greeting_context.py`、`storage/feedback_repository.py`、`storage/pipeline_metrics.py` | 批准 → Jobs `批准状态`；审计 → Jobs 执行结果；lease → 执行技术租约 | approvals/asks: retire；audits/batches: migrate；leases: keep（非权威）；`outreach_audits_next`: retire（**孤立表，无任何代码引用**） |
| 对话 / HR 来信 | 0005, 0010 | `conversations`, `conversation_events`, `conversation_asks`, `conversation_receipts` | `storage/conversation_repository.py`、`bridge/status.py` | 未定义域 | confirm |
| 巡检 | 0006–0008 | `patrol_checks`, `patrol_finishes`, `patrol_snapshots` | `storage/patrol_repository.py`、`bridge/status.py` | 运行检查点 → Jobs / Workflow 或标准日志 | retire（检查点迁入后） |
| 寻源预算与详情记账 | 0014, 0029, 0032 | `sourcing_runs`, `sourcing_attempts`, `sourcing_results`, `sourcing_legacy_reads`, `sourcing_read_attempts`, `sourcing_read_halts`, `sourcing_query_selections`, `sourcing_seen_listings`, `sourcing_query_claims` | `storage/sourcing_repository.py`、`storage/read_repository.py`、`storage/query_repository.py`、`storage/mcp_repository.py`、`storage/job_intake_service.py`、`storage/host_reports.py` | 执行检查点（额度、限流停站、去重） | confirm（`AGENTS.md` 要求按实际尝试记账） |
| 已发跟踪 | 0017 | `sent_tracking_roots`, `sent_tracking_events`, `sent_tracking_requests`, `sent_tracking_sends` | `storage/sent_tracking_repository.py`、`storage/pipeline_service.py` | Jobs 执行结果 / 平台反馈 | migrate |
| 人工加岗 | 0018 | `job_intakes`, `intake_events`, `intake_requests`, `intake_signals`, `intake_active_strategies`, `intake_strategy_claims`, `intake_search_executions`, `intake_selections` | `storage/job_intake_repository.py`、`storage/job_intake_service.py`、`storage/intake_strategy.py`、`storage/pipeline_sync.py` | Human 直接在 Jobs 增岗 | migrate → retire |
| 宿主迁移 / 回填 | 0019, 0020 | `host_migration_runs`, `host_legacy_rows`, `host_page_observations`, `host_round_reports`, `host_backfill_links` | `storage/host_migration.py`、`storage/host_backfill.py`、`storage/host_checks.py`、`storage/host_reports.py` | 一次性迁移工具；轮次报告 → Jobs / 日志 | retire |
| 文案差异 / Confirmed Rules | 0021 | `message_diff_events`, `message_rule_proposals`, `message_rule_confirmations` | `storage/message_diff_repository.py`、`storage/pipeline_rules.py` | 差异 → Human Signals / SignalAssessment；已确认规则 → Greeting MemoryRule | migrate |
| Pipeline | 0022–0026 | `pipeline_jobs`, `pipeline_authorities`, `pipeline_meta`, `pipeline_state_history`, `pipeline_requests`, `pipeline_observations`, `pipeline_used_sends`, `pipeline_rejections`, `pipeline_migration_runs`, `pipeline_migration_rows`, `pipeline_stage_metrics`, `pipeline_diagnoses`, `pipeline_metric_context`, `pipeline_diagnosis_reports`, `pipeline_rule_reviews`, `pipeline_backfill_links` | `storage/pipeline_*.py`、`console/projection.py`、`storage/host_*`、`storage/sent_tracking_repository.py` | Jobs `处理进度 × 批准状态` + Record History | retire（Phase 3 后）；指标/诊断 confirm（可由 Bitable 派生） |
| Worker | 0027 | `worker_fetch_receipts`, `worker_send_claims`, `worker_events`, `worker_event_acks` | `storage/worker_repository.py`、`bridge/worker.py` | 执行检查点 → Jobs；claim 幂等可保留为本地技术租约 | migrate（结果）/ keep（租约，非权威） |
| 面板反馈 / 选择 / 执行批 | 0028, 0029, 0035–0038 | `paged_card_states`, `paged_card_events`, `sourcing_feedback_events`, `sourcing_feedback_strategies`, `feedback_strategy_heads`, `feedback_consumptions`, `outreach_feedback_links`, `panel_operations`, `execution_batches`, `execution_confirmations`, `panel_selection_versions` | `storage/feedback_repository.py`、`storage/execution_repository.py`、`console/selection.py`、`console/outreach.py`、`bridge/panel_decisions.py` | 反馈事件 → Human Signals；面板状态 → Bitable Views | sourcing_feedback_events: migrate；其余 retire |
| 动态变量 / 首次配置 | 0030, 0031 | `dynamic_rule_proposals`, `dynamic_rule_versions`, `dynamic_rule_heads`, `dynamic_rule_confirmations`, `dynamic_rule_announcements`, `configuration_initializations`, `configuration_owner_consumptions` | `storage/rule_repository.py`、`storage/configuration_repository.py`、`storage/pipeline_policy.py`、`bridge/dynamic_rules.py`、`console/onboarding.py` | 私有配置，**不是偏好 Memory** | confirm（建议 keep 为私有配置） |
| MCP 实际调用网关 | 0033 | `mcp_rounds`, `mcp_round_activations`, `mcp_round_closures`, `mcp_batches`, `mcp_calls`, `mcp_dispatches`, `mcp_results`, `mcp_reconciliations`, `mcp_delivery_actions`, `mcp_delivery_observations`, `mcp_delivery_reconciliations` | `storage/mcp_repository.py`（843 行） | 执行检查点 / 调用额度 | confirm |
| 公开招聘页发现 | 0034 | `public_career_runs`, `public_career_records`, `public_career_http`, `public_career_stops` | `storage/public_careers_repository.py`、`console/public_careers.py` | 发现结果 → Jobs；HTTP 停站 → 执行检查点 | migrate / confirm |
| 方向门禁 | 0039 | `direction_proposals`, `direction_answers` | `storage/direction_repository.py`、`bridge/preference_memory.py` | 本人回答 → Human Signals | migrate |

合计 123 张表；孤立表 1 张（`outreach_audits_next`）。

## 2. 直接使用 `sqlite3` 的非 storage 模块

这些模块在 `storage/` 之外直接持有连接或执行 SQL，是退役时最容易遗漏的地方：

| 模块 | 用途 | 处理 |
|---|---|---|
| `bridge/status.py` | MCP `status_today` / `pending_approvals` / `patrol_history` / `new_jobs` 手写 SQL | migrate → Bitable 查询 |
| `bridge/mcp_server.py` | 默认数据库路径；调用 status 与 projection | migrate |
| `bridge/worker.py` | 本地事务（claim / audit / event） | migrate（结果回写 Bitable） |
| `bridge/preference_memory.py` | 读 owner 事件（outreach / evidence / direction） | retire |
| `bridge/memory_sources.py` | 只读外部私有 SQLite 源 | retire |
| `bridge/greeting_context.py`、`bridge/greeting_freshness.py` | 读取候选人、岗位、批次组装上下文与复核 | migrate（读 Jobs / Materials） |
| `bridge/roleplay.py` | 合成评测创建临时库 | confirm（评测改用 Bitable Mock） |
| `bridge/dynamic_rules.py` | 读动态变量快照 | confirm |
| `console/*.py`（6 个） | 投影、选择、onboarding、公开招聘页 | retire |
| `cli/*.py`（23 个） | `--database` 选项与事务 | 随各域迁移改造 |

## 3. 本地文件与目录

| 文件 | 写入方 | 消费者 | 性质 | 处理 |
|---|---|---|---|---|
| `.jobagent/jobagent.sqlite3` | `storage/database.py` | 64 个源模块 | 当前业务权威 | 按 §1 分域退役 |
| `.jobagent/runs/<run_id>/state.json` | `storage/harness_store.py` | `cli/harness.py`、`console/activities.py` | Harness 会话租约与跨宿主恢复 | keep（技术用途，声明非业务权威）/ confirm |
| `console-activities.json`（运行目录内） | `console/activities.record_activity` | `console/projection.py`、`cli/console.py event` | 宿主活动观察 | retire（随 Console） |
| 偏好 Markdown（`memory_path`，私有）+ `history/<version>.md` + `.lock` | `bridge/preference_memory.MarkdownPreferenceStore` | `jobs search-plan --memory-settings`、`greetings generate`、`roleplay` | 旧偏好 Memory 生产真相 | migrate（一次性迁移）→ retire |
| `.jobagent/preference-runtime/` | `cli/jobs.py`、`cli/greetings.py` | Codex 子进程工作目录 | 临时 | keep |
| 发布 Memory JSON（`--search-memory`，`PublishedMemoryFile`） | `memory signal-compile` | `jobs search-plan` | 本地 JSON Search Memory | retire |
| Signal 接收 JSON（`SignalReceiptFile` / `HumanSignalFile`） | `memory signal-receive` | `memory signal-compile` | 本地 fixture 解析 | retire（测试 fixture 保留） |
| Memory 源配置与快照（`MemoryConfig.private_root`） | `storage/memory_repository.py` | `memory status/compile/context` | P1 只读编译快照 | retire |
| `cowork_inbox.jsonl`、`cowork_inbox_done.jsonl`、`cc_outbox.jsonl`、`agent_peers.json` | `bridge/mailbox.py` | MCP `post_to_claude_code` 等 | Cowork ↔ Claude Code 邮箱 | confirm |
| Codex 运行文件 `output-schema.json` / `result.json` | `bridge/codex_runner.py` | 自身 | 临时 | keep |
| `greetings` 运行目录 `request.json` / `report.json` / `drafts.json` | `cli/greetings.py` | 宿主 | 运行产物 | keep（非权威） |

## 4. 退役前置条件（每张业务表）

1. 对应 Bitable 域字段在语义映射中存在且类型兼容（Phase 2）。
2. 所有写入方改为 Bitable Gateway 并有写后回读测试（Phase 3/5）。
3. 所有读取方改为 Bitable 或删除；`rg "<table>" src/` 无命中。
4. 一次性导出工具（dry-run → 本人确认 → 写入 → 回读对账）完成，或明确判定无需迁移数据。
5. 删除 migration 时保留 `storage/database.py` 对历史库的兼容策略（拒绝打开 / 只读导出），不得让旧库被静默当成空库。
