# Phase 0：全仓现状审计（只读）

日期：2026-11-21。本轮只读：没有改生产代码，没有读写真实飞书 Base，没有启用 Workflow，没有发送招聘消息，没有修改任何远端分支或 PR。本文件与同目录另外三份报告是本轮唯一新增内容。

配套报告：

- [旧存储盘点](legacy-storage-inventory.md)：39 个 migration、123 张 SQLite 表、本地文件，逐项给出 keep / migrate / retire / confirm。
- [Memory 接线盘点](memory-wiring-inventory.md)：新旧 Memory、Signal、Dream、Publish、Fetch Pin 的 Schema、入口、测试与消费者。
- [消费者依赖图](consumer-dependency-map.md)：React / Console / Projection / MCP / CLI / Worker / Search Plan / Greeting 的真实调用链与迁移依赖。

## 1. 基线核对

| 项 | 实测值 |
|---|---|
| 工作分支 | `claude/busy-darwin-s3vgn2`，HEAD `32575f37c1b5`，工作区干净 |
| `origin/main` | `32575f37c1b56eda58dfe39a6929c3f81501f44b`（Merge PR #32） |
| PR #36 | open，非 draft，`cursor/memory-workflow-alignment-9cb3`，head `f3eb0222a16067c354ef193ee9f04d74b815803d`；与任务书记录一致 |
| PR #36 与 main | merge-base 即 main HEAD；领先 16 个提交，落后 0；50 个文件，+8594 / −68，没有删除旧实现 |
| PR #36 叠加关系 | 包含 PR #34 head `fe5394b`（Feishu adapter）与 PR #35 head `36836e9`（Signal / Worker gate）；三者不应分别合并 |
| PR #36 远端 CI | `python` check 失败，2 秒结束（02:54:15→02:54:17），与 PR 描述的 Runner 未分配一致；**无远端执行证据** |
| Issue #37 | open；工作包 A 的代码项（`jd_digest`、表 ID 来自私有 `FeishuConfig`、去掉 Records 必需性、按语义字段校验）已在 `f3eb022` 中核对到；A 的真实 Schema 只读核验、B/C/D 均未开始 |
| 其他 open PR | #33（CV/招呼文案，draft）、#31（清理提案）、#14（旧 React UI）、#6/#7（早期 Muse 本地宿主） |

**main 与 PR #36 的事实差异**：main 的 `AGENTS.md` 写明“仓库不再内置飞书桥接”，`src/` 中无任何 Feishu 代码；全部 Bitable 能力只存在于 PR #36（及其包含的 #34/#35）。因此本审计以 PR #36 head 为代码基线，main 为文档基线。

### 本机门禁（PR #36 head，Python 3.13.18，干净 venv）

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest -q -p no:cacheprovider` | 2141 passed, 4 skipped | 0 |
| `python -m ruff check .` | All checks passed | 0 |
| `python -m mypy src/jobagent` | no issues in 290 source files | 0 |

跳过项：3 个 `tests/reasoning/test_output_schemas.py`（未安装可选依赖 `anthropic`）、1 个 `tests/rendering/test_resume.py:95`（本机无 CJK 字体）。PR 描述记录的是 Python 3.12 下 2142 passed / 3 skipped；差异即这 1 个字体相关跳过，不是失败。以上均为 Mock / Unit / Contract 级别，**没有任何 Real Feishu 验证**。

## 2. 规模

| 范围 | 数量 |
|---|---|
| `src/jobagent` Python | 290 个文件，约 50,900 行 |
| `src/jobagent/storage` | 44 个文件；39 个 migration，123 张表 |
| 直接 `import sqlite3` 的源模块 | 46 |
| 依赖 `storage.database` 的源模块 | 64；测试文件 61 |
| `src/jobagent/console` | 11 个文件；`schemas/console*.py` 2 个 |
| `frontend/`（React 19 + Vite + Playwright） | 53 个文件（不含 node_modules） |
| CLI 子命令组 | 23（含 `memory`、`feishu`、`worker`、`console`） |

## 3. 核心结论

1. **当前生产路径的业务权威仍是 SQLite**。Jobs、Pipeline、Outreach 批准、审计、对话、寻源记账、Candidate Evidence、动态变量全部落在 `.jobagent/jobagent.sqlite3`；Bitable 只在 PR #36 中以“旁路”接入两处：Worker 发送前读取共享记录（`jobs/shared_send_gate.py`），以及 `memory` 命令组读写 Human Signals / Search Memory / Greeting Memory。
2. **Worker 是唯一已部分切换到 Bitable 裁决的执行路径**：`bridge/worker.py` 在 claim/authorize 前重新读取共享记录并以 `ApprovalChannel.SHARED_TABLE` 合成批准，不再查本地 approval；但 claim、audit、lease、event 仍写 SQLite，执行结果**不回写 Bitable**（无 patch 调用）。
3. **两套 Memory 并行存在且互不知晓**：旧 `PreferenceLearner` + `MarkdownPreferenceStore`（本地 Markdown，`jobs search-plan --memory-settings`、`greetings generate` 生产在用）与新 `SharedMemoryService`（Bitable 单记录快照，`memory search-round/fetch-pin`）。`jobs search-plan` 同时接受 `--memory-settings` 与 `--search-memory`（本地 JSON），三条来源都可生效。
4. **Greeting Memory 只有发布与解码，没有 Dream 与消费者**。Search Memory 有完整的冻结批次 → 发布 → Pin 契约，但 Dream 推理由宿主执行（`host_delegated`），真实闭环未验收。
5. **Console / React 依赖 SQLite 投影**：React → `console serve`（loopback GET）→ `console.projection.snapshot` → SQLite；MCP `console_snapshot` 与 `status_*` 工具也直读 SQLite。退役 Console 必须先迁移 MCP。
6. **新增发现：任务书与仓库现实的三处语义错位**，需要本人裁定（见 §5）。

## 4. 差距矩阵

状态取值：`implemented`（代码 + 测试存在，生产入口可用）/ `partially_wired` / `not_integrated` / `host_delegated` / `blocked` / `unverified`（代码存在但无真实 Feishu / 宿主验证）。

### 4.1 Bitable Access 与 Initial Setup

| 能力 | 状态 | 证据 |
|---|---|---|
| Feishu Gateway（官方 `lark-cli` 子进程，argv 不经 shell） | implemented / unverified | `bridge/feishu_gateway.py`，`tests/bridge/test_feishu_gateway.py`（Mock Transport） |
| `FeishuConfig` 私有配置（表、字段、可写字段、角色白名单） | implemented | `schemas/feishu.py`；表 ID 不再写死 |
| Schema 读取（字段列表/类型） | partially_wired | `FeishuGateway.schema()`；无“发现 → 映射五个语义域 → 差异展示 → 确认”流程 |
| Initial Setup Box / Skill Bootstrap | not_integrated | 无命令；`rules initialize` 只管动态变量 |
| Tunnel 建立或复用 | host_delegated | 仓库内无 Tunnel 代码；`lark-cli auth status` 由宿主执行 |
| Record list/query/get | implemented / unverified | `query` 分页（`has_more`/offset）、`get` 单条强校验 |
| Record create | partially_wired | 仅 `append_memory_row`（Memory 表首建） |
| Record update + 回读 | partially_wired | `patch` 仅 text/select，写后回读；超时标 `dispatch_outcome_unknown_do_not_repeat` |
| 字段类型校验/转换 | partially_wired | `_reject_cell` 只覆盖 text/select；Human Signals 按映射语义字段校验类型 |
| Record History 归因 | implemented / unverified | `memory/history_match.py`，open_id / union_id 对照 `OperatorDirectory`，显示名一律 unknown |
| Workflow 绑定 | partially_wired | `DisabledWorkflowBinding` 只接受 `enabled=false`；无启用、无状态迁移执行 |
| 限流 / 重试 | not_integrated | 无 rate limit；未知写入明确不重试（符合护栏） |
| 权限 / 只读字段探测 | partially_wired | `writable` 白名单 + `validate_permissions`；无线上权限探测 |

### 4.2 全局状态机

| 能力 | 状态 | 证据 |
|---|---|---|
| `处理进度 × 批准状态` 联合解释 | partially_wired | `jobs/shared_send_gate.current_work_decision` 只服务 Worker 首条招呼 |
| 状态迁移矩阵 | not_integrated | 本地 `schemas/pipeline.PipelineState` 仍是 SQLite 枚举；无 Bitable 映射 |
| Generation 写草稿/评估到 Jobs | partially_wired | `feishu patch` 可写配置白名单字段；`greetings generate`、`jobs` 评估结果仍写 SQLite |
| Human 批准消费 | partially_wired | Worker 消费；`console decide`、`outreach approve`、`applications` 仍走 SQLite 审批 |
| Execution 回写 Bitable + 回读 | not_integrated | `worker record-greeting` 只写本地 audit/event |
| 必要执行检查点进 Bitable | not_integrated | 检查点全部在 SQLite（worker_*、mcp_*、sourcing_*、patrol_*） |

### 4.3 Human Signal / Dream / Memory

| 能力 | 状态 | 证据 |
|---|---|---|
| Workflow 写入的 Human Signals 行解析 | implemented / unverified | `memory/workflow_signal.py`，`memory workflow-page` |
| Signal 归因补全（History before/after + 操作者） | implemented / unverified | `SharedMemoryService.enrich_signal` |
| SignalAssessment（Observation / Motivation / 开放维度 / disposition） | not_integrated | 现有 `SignalPreferenceDelta` 只有 add/remove + reason；`signal_type` 为封闭集合 |
| Search Dream 冻结批次 / 恢复 / 窗口 | implemented（服务端）/ host_delegated（推理） | `dream-batch-start/complete`，`references/memory-dream.md` |
| Greeting Dream | not_integrated | 只有 `greeting_memory` 发布与解码 |
| MemoryRule / MemoryChangeSet（统一） | not_integrated | 旧 `PreferenceRule`/`PreferenceEditSet` 有 add/edit/merge/retire；新快照是 keywords/directions/exclusions 平铺，无 rule_id |
| 单记录原地更新、version+1、hash、source_signal_ids、回读 | implemented / unverified | `memory/publication.py`、`publish-version` |
| 无净变化不发布 | implemented | Dream complete no-op 路径 |
| Fetch Pin | implemented / unverified | `memory fetch-pin/fetch-continue` |
| Search Plan 读取 Bitable Search Memory | not_integrated | `jobs search-plan` 只读本地 Markdown / 本地 JSON；`memory search-round` 是独立命令 |
| Matching / Greeting / CV / Profile / Interview 读取 Bitable Memory | not_integrated | Greeting 读本地 Markdown；CV/Profile/Interview 不读 Memory |
| Consumer Provenance | partially_wired | 旧 outreach batch 记录 `memory_version`；无 hash / rule_ids 写入 Bitable |

### 4.4 退役对象

| 对象 | 状态 |
|---|---|
| Worker SQLite 业务账本 | 仍在生产使用 |
| Console Projection / Server / React | 仍在使用；MCP 依赖 projection |
| `bridge/status.py` SQLite 查询 | 仍被 MCP 4 个工具使用 |
| `MarkdownPreferenceStore` / `SignalInbox` / `SignalCompiler` | 前者生产在用；后两者已降级为 fixture 测试工具但 CLI 仍暴露 |
| 旧 Events / Records 通知表 | 代码不再依赖（PR #36 已去掉必需性） |
| `state.json` | 仅 Harness 运行租约/恢复（`.jobagent/runs/<id>/state.json`），不是业务状态 |

## 5. 需要本人裁定的冲突（confirm）

以下事项属于“最新用户决策与仓库硬性约束/现实冲突”，按 §0.1 不能由助手自行决定：

1. **Candidate Evidence → Materials 与 AGENTS.md 硬性边界冲突。** `AGENTS.md` 规定“只有 `CandidateEvidenceService.confirm` 能提升 canonical Evidence”。任务书要求 Materials 在 Bitable、SQLite 退役。可选：(a) 保留 `CandidateEvidenceService` 作为唯一提升入口，把存储后端换成 Bitable Materials（推荐，护栏不变）；(b) 本人在 Bitable 中直接确认事实，`confirm` 改为读取并核验 Bitable 中的人工确认记录。两者都需要修改 `AGENTS.md`。
2. **“Dynamic Rules” 不是偏好 Memory。** 仓库中的 `rules` / `dynamic_rule_*` 是**动态变量**（查询次数、`TOP_PER_QUERY`、轮询时间、比例阈值等，见 `rules/registry.py`），不是写作或搜索偏好。任务书 §8.2 把它映射到 MemoryRule 会把配置当偏好学习。建议：动态变量保持为私有配置（SQLite 或私有文件，非业务权威），不迁入 Memory；真正需迁移的是 `message_rule_*`（Confirmed Rules）和 `PreferenceRule`。
3. **五个语义域未覆盖的现有业务数据。** 对话/HR 来信（`conversations*`）、投递审计（`application_audits`）、寻源预算与详情访问记账（`sourcing_*`、`mcp_*`，`AGENTS.md` 要求“详情访问按实际尝试记账”）、公开招聘页发现（`public_career_*`）、Profile 飞轮（`profile_*`）没有对应 Bitable 域。需决定：并入 Jobs 字段、作为 Jobs 的附属表（需新建表，属于 Schema 变更）、还是作为非权威执行检查点保留本地。
4. **开发分支基线。** Phase 1 起的代码改动依赖 PR #36 的 Feishu / Memory 代码，而本分支基于 main。建议把 PR #36 head `f3eb022` 合入本开发分支（不改动 PR #36 远端分支、不合并 PR 本身），后续 PR 以 #36 为 base 或在 #36 合并后 rebase。
5. **`AGENTS.md` 现行约定与新架构矛盾。** main 的 `AGENTS.md` 仍写“决定经 `console decide` 写入私有 SQLite，由它驱动审批门禁”“仓库不再内置飞书桥接”“React 控制台与飞书同级前端”。这些是 Phase 1 必须改写的仓库规范，属于对工程纪律文件的实质修改。

## 6. keep / migrate / retire / confirm 总表

细项见各配套报告；此处为模块级汇总。

| 处理 | 模块 |
|---|---|
| **keep** | `bridge/feishu_gateway.py`、`schemas/feishu.py`、`memory/history_match.py`、`memory/workflow_signal.py`、`memory/publication.py`、`memory/snapshot.py`、`memory/search_round.py`、`bridge/shared_memory.py`（Dream 批次 / 发布 / Pin）、`jobs/shared_send_gate.py`、`jobs/search_memory_apply.py`、`bridge/greeting_freshness.py`、`bridge/greeting_policy.py`、`outreach/generation.py`、candidate / optimizer / harness / connectors 领域逻辑、Worker 的未知结果保护与幂等逻辑 |
| **migrate**（能力迁移后旧实现退役） | `outreach/preference_memory.PreferenceLearner`（update/select/direction）、`schemas/preference_memory`（PreferenceRule/EditSet → MemoryRule/ChangeSet）、`jobs/message_diff.py` + `storage/message_diff_repository.py`（→ SignalAssessment）、`memory/usage.py` / `effect.py` / `simulation.py`（→ Bitable version / provenance）、`bridge/status.py`（→ Bitable 查询）、`bridge/mcp_server.py`（换数据源）、`bridge/worker.py` / `bridge/panel_decisions.py`（回写 Bitable）、Jobs / Pipeline / Outreach / Sent-tracking / Job-intake / Public-careers 仓储（→ Jobs 表）、`storage/candidate_repository.py`（→ Materials，见 §5.1）、`storage/direction_repository.py` / `sourcing_feedback_*`（→ Human Signals） |
| **retire**（替代路径验收后） | `bridge/preference_memory.MarkdownPreferenceStore`、`memory/service.py` + `storage/memory_repository.py` + `bridge/memory_sources.py`（P1 统一 Memory 只读编译层）、`memory/signal.py` `SignalInbox` 与 `memory/signal_compile.py`（CLI 入口）、`jobs search-plan --memory-settings/--search-memory`、`console/` 全部 + `cli/console.py` + `schemas/console*.py`、`frontend/`、`storage/pipeline_*`、`storage/host_migration/backfill/*`、panel / paged-card / execution-batch / selection 表、`outreach_audits_next`（孤立表，无引用） |
| **confirm** | Candidate Evidence 存储（§5.1）、动态变量存储（§5.2）、conversations / applications / sourcing / mcp / public-careers / profile 的归属（§5.3）、`bridge/mailbox.py`（Cowork 邮箱，本地 jsonl）、`storage/harness_store.py`（运行租约 `state.json`，技术用途可保留）、`jobs/search_learning.py` / `sourcing_feedback.py`（确定性优先级更新，是否并入 Search Dream）、`roleplay` / `codex_runner` / `gemini_runner`（评测与推理宿主工具，保留但改数据源） |

## 7. 实施顺序（修订）

任务书 Phase 1–7 顺序合理，结合实测依赖做如下细化：

| 阶段 | 内容 | 前置 | 是否触碰真实 Feishu |
|---|---|---|---|
| 1 | 架构契约：Global State Machine ADR、Bitable Semantic Mapping、Materials / Human Signal / SignalAssessment / MemoryRule / MemoryChangeSet / Publication / Provenance / Legacy Migration 契约（`schemas/` 新增 Pydantic 模型 + 测试），改写 `AGENTS.md` 相关段落 | §5 裁定；PR #36 合入开发分支 | 否 |
| 2 | Bitable Access 补全（create / 更多字段类型 / Schema Discovery → 语义映射差异 / Initial Setup 命令 / 只读验收命令） | 1 | 只读验收需本人授权；本环境无凭证 → `unverified` |
| 3 | 状态机接线：状态迁移矩阵；Worker 结果回写 + 回读；`console decide` / `outreach approve` / `applications` 改为读 Bitable 批准；Pipeline 改读 Jobs | 2 | 否（Mock） |
| 4 | Sensemaking：SignalAssessment、开放维度、disposition 分流、Greeting Dream 批次、误记评测 18 例 | 1、2 | 否 |
| 5 | 旧 Memory 迁移工具（dry-run）+ 消费者接线：`search-plan` → Bitable Search Memory + Pin；Greeting / Matching 读 Bitable；Provenance 写 Jobs | 3、4 | 迁移写入需本人确认 |
| 6 | 退役：先 MCP 改数据源 → Console / Projection / Server / React → `status.py` → SQLite 业务仓储与 migration → 旧 Memory 文件存储 | 3–5 全部通过 | 否 |
| 7 | 全仓验收：全套测试 / Ruff / mypy / 引用扫描 / 迁移对账 / 文档 / 最终 ADR | 6 | 有授权时做 Real Feishu Contract |

关键路径：MCP 对 `console.projection` 与 `bridge/status.py` 的依赖必须在 Phase 3 提供 Bitable 版本，Phase 6 才能删 Console；`greetings generate` 与 `jobs search-plan` 必须在 Phase 5 切换后，才能删 `MarkdownPreferenceStore`。

## 8. 未验证与阻塞

- 本环境没有 Feishu 凭证与 `lark-cli`；所有 Bitable 能力只能达到 Mock / Contract 级别，标记 `unverified`。
- 远端 CI 无法分配 Runner，PR 门禁只有本机证据。
- 宿主任务（Muse / GPT 定时任务、Dream 03:00 调度）正文不在仓库，无法核验实际加载版本；`hosts/personal-ai/tasks.md` 是规范，不是部署证据。
- 真实 Bitable 表结构（五个语义域的实际字段）未知；语义映射只能以契约 + 合成 fixture 实现。
