# Memory 接线盘点：旧 Memory、新 Memory、Signal、Dream、Publish、Fetch Pin

基线：PR #36 head `f3eb022`。“生产入口”指 `jobagent` CLI 中会被宿主任务调用、并影响真实业务输出的命令；“测试”列出直接 import 该模块的测试文件（相对 `tests/`）。

## 1. 现存四代 Memory 实现

| 代际 | 核心模块 | 存储 | 生产入口 | 当前是否影响业务输出 |
|---|---|---|---|---|
| G1 偏好 Memory | `outreach/preference_memory.py`（`PreferenceLearner` update/select/direction）、`bridge/preference_memory.py`（`MarkdownPreferenceStore`、owner 事件读取、`refresh_preference_memory`）、`bridge/preference_reasoning.py`（Codex 文本推理）、`schemas/preference_memory.py` | 私有 Markdown + `history/`；owner 事件来自 SQLite（outreach / evidence / direction） | `jobs search-plan --memory-settings`、`greetings generate`（配置含 `memory_path` 时）、`roleplay` | **是**：改变检索词、跳过建议（direction）、招呼语上下文 |
| G1′ 文案差异与已确认规则 | `jobs/message_diff.py`、`storage/message_diff_repository.py`、`storage/pipeline_rules.py`、`schemas/message_diff.py` | SQLite `message_diff_events`、`message_rule_*` | `host` 子命令、`pipeline rule-propose/rule-confirm/confirmed-rules` | 间接：已确认规则进入 pipeline 规则复核 |
| G2 P1 统一 Memory（只读编译） | `memory/service.py`、`memory/selection.py`、`memory/ports.py`、`storage/memory_repository.py`、`bridge/memory_sources.py`、`schemas/memory.py` | 私有源配置 + 快照文件；只读外部 SQLite / Markdown | `memory status/compile/context` | 否：只汇编上下文供宿主阅读 |
| G3 本地 Signal 编译 | `memory/signal.py`（`SignalInbox`）、`memory/signal_compile.py`（`SignalCompiler`、`FileAttributor`）、`schemas/memory_signal.py` | 本地 JSON | `memory signal-receive/signal-compile/apply-search/send-gate`；`jobs search-plan --search-memory` | **是**（若宿主传 `--search-memory`）；PR #36 已声明其不再是生产事件路径 |
| G4 Bitable 共享 Memory | `bridge/shared_memory.py`（`SharedMemoryService`）、`memory/workflow_signal.py`、`memory/history_match.py`、`memory/publication.py`、`memory/snapshot.py`、`memory/search_round.py`、`jobs/search_memory_apply.py`、`schemas/shared_memory.py`、`bridge/feishu_gateway.py` | Feishu Bitable：Human Signals、Search Memory、Greeting Memory（表 ID 来自私有 `FeishuConfig`） | `memory workflow-page/enrich-signal/publish-version/search-round/dream-batch-start/dream-batch-complete/fetch-pin/fetch-continue` | 否：独立命令，尚无生产消费者调用 |

此外有两条“类 Memory”的确定性学习链，不在任务书清单中但属于同一问题域：

| 模块 | 作用 | 存储 | 处理建议 |
|---|---|---|---|
| `jobs/search_learning.py` | 从原始信号重算可逆搜索假设 | SQLite（sourcing / intake） | confirm：并入 Search Dream 或保留为确定性预处理 |
| `jobs/sourcing_feedback.py` + `storage/feedback_repository.py` | 依据本人反馈确定性调整寻源优先级（`sourcing_feedback_*`、`feedback_strategy_heads`） | SQLite | migrate：反馈事件 → Human Signals；策略 → Search MemoryRule |
| `storage/direction_repository.py` | 方向门禁提议与本人回答 | SQLite `direction_*` | migrate → Human Signals |

## 2. 模块级详单

| 模块 | 行数 | src 消费者 | 测试 | 处理 |
|---|---:|---|---|---|
| `outreach/preference_memory.py` | 311 | `bridge/preference_memory`、`bridge/preference_reasoning`、`bridge/roleplay`、`cli/greetings`、`cli/jobs`、`outreach/generation` | `bridge/test_preference_memory.py`、`memory/test_memory_loop.py`、`outreach/test_direction_answers.py`、`outreach/test_preference_edits.py`、`outreach/test_preference_memory.py` | migrate（update → Dream；select → 任务级规则选择；direction → Matching 上下文） |
| `bridge/preference_memory.py` | 393 | `bridge/memory_sources`、`bridge/roleplay`、`cli/greetings`、`cli/jobs` | 10 个测试文件 | retire（Markdown 存储）；owner 事件核验逻辑迁到 Signal Attribution |
| `bridge/preference_reasoning.py` | 142 | `bridge/roleplay`、`cli/greetings`、`cli/jobs` | `bridge/test_preference_reasoning.py` | migrate（文本推理提示迁到 Dream / Selection 宿主契约） |
| `schemas/preference_memory.py` | 173 | 6 个 src 模块 | 11 个测试文件 | migrate → `MemoryRule` / `MemoryChangeSet`（保留 rule_id、scope、condition、forbidden_phrases、source ids、add/edit/merge/retire） |
| `jobs/message_diff.py` | — | `cli/host` 等 | `jobs/test_message_diff.py` | migrate → SignalAssessment 的 Before/After 差异片段 |
| `storage/message_diff_repository.py` | 239 | `bridge/memory_sources`、`cli/host`、`storage/pipeline_rules` | `storage/test_message_diff.py`、`storage/test_pipeline_policy.py`、`workflows/test_pipeline_flywheel.py` | migrate（一次性导出）→ retire |
| `memory/service.py` / `storage/memory_repository.py` / `bridge/memory_sources.py` / `memory/selection.py` / `memory/ports.py` | 124 / 97 / 270 / 37 / 17 | 仅 `cli/memory` | `memory/test_context.py` | retire；`selection.py` 的确定性 scope 过滤迁到新 Selection |
| `memory/signal.py` | 291 | `cli/memory` | `memory/test_memory_signal.py`、`bridge/test_shared_memory_alignment.py` | retire CLI 入口；fixture 解析保留为测试工具 |
| `memory/signal_compile.py` | 214 | `cli/memory` | `memory/test_memory_signal.py` | retire（字段→偏好类校验思路迁到 Attribution） |
| `memory/usage.py` / `effect.py` / `simulation.py` | 70 / 189 / 48 | `cli/memory`、`bridge/roleplay` | `memory/test_memory_loop.py`、`memory/test_effect*.py`、`outreach/test_generation_provenance.py` | migrate：改读 Bitable Memory version / hash / Provenance |
| `bridge/shared_memory.py` | 1103 | `cli/memory` | `bridge/test_dream_batch.py`、`bridge/test_shared_memory_alignment.py` | keep；拆分 Search / Greeting Dream，接入 SignalAssessment |
| `memory/workflow_signal.py` / `history_match.py` / `publication.py` / `snapshot.py` / `search_round.py` | 117 / 243 / 219 / 73 / 73 | `bridge/shared_memory`、`bridge/feishu_gateway` | `bridge/test_shared_memory_alignment.py`、`bridge/test_history_match.py`；`search_round` 无直接测试 | keep；`publication` 字段扩展为 MemoryRule 快照 |
| `jobs/search_memory_apply.py` | 101 | `cli/jobs`、`bridge/shared_memory`（经 search_round） | `memory/test_memory_signal.py` | keep；成为 `search-plan` 唯一 Memory 应用点 |

## 3. 新 Memory（G4）的已实现能力与缺口

已实现（Mock / Contract 级，全部 `unverified`）：

- Human Signals 行解析：唯一标识为行 `record_id`；`signal_type ∈ {matching_correction, greeting_revision, workflow_outcome}`，`memory_domain ∈ {search_match, greeting, workflow_context}`。
- 归因：History 读完整页；同字段恰好一次可读 before/after，操作者 open_id / union_id 命中名单才 `matched`；显示名、不唯一、历史未读完 → `unknown` 或失败。
- Dream 批次：冻结窗口与 Signal ID、恢复必须复用原窗口、每个 Signal 恰好一个 delta、候选人归属校验、进程内锁。
- 发布：每候选人每域一条记录；首次 create，后续原地 update；`version+1`、`content_hash`、`source_signal_ids`、写后回读；超时通过回读识别；无净变化不增版本；`jd_digest` 为来源 JD 正文摘要。
- Fetch Pin：`search-round` 读当前版本；`fetch-pin` 固定版本与 hash；`fetch-continue` 校验 Pin 未漂移；`grants_fetch=false`。

与任务书目标的缺口：

| 目标 | 缺口 |
|---|---|
| SignalAssessment（Observation / Motivation / Rule Formation） | 只有 `SignalPreferenceDelta`（add / remove 关键词、方向、排除 + reason）；无 motivation、alternatives、scope_hypothesis、disposition、counterevidence |
| 开放式行为类型与维度 | `SignalType`、`MemoryDomain` 为封闭 `Literal`；新类型会被拒绝 |
| MemoryRule 快照 | Search 快照是 keywords / role_directions / exclusions 平铺列表；Greeting 快照只有 `notes`；无 rule_id、scope、maturity、enforcement、evidence / counterexamples |
| MemoryChangeSet | 新路径无 add / edit / merge / retire；旧 `PreferenceEditSet` 有但未接入 |
| Greeting Dream | 无批次、无推理契约、无消费者 |
| `forbidden_phrases` 确定性检查 | 只在 G1（`PreferenceRule`）中存在 |
| 生产消费者 | `jobs search-plan`、`greetings generate`、Matching、CV / Profile / Interview 均未读取 G4 |
| Provenance | 无 selected_rule_ids / content_hash 写入 Jobs |
| 跨进程 / 跨宿主 Dream 租约 | 仅进程内锁；文档要求宿主持有候选人级租约 |

## 4. 旧能力 → 新归属映射（实测修订版）

| 旧能力（实际代码） | 新归属 | 迁移要点 |
|---|---|---|
| `PreferenceLearner.update`（事件 → `PreferenceEditSet`，模型提议、程序校验） | Dream → `MemoryChangeSet` | 保留“模型提议 / 程序校验 / 未提及不删除 / 每条规则可追溯事件”；事件来源改为 Human Signals |
| `PreferenceLearner.select`（按 task / job 选规则，产出 `PreferenceSelection`） | Task-specific Memory Selection | 保留 `memory_version` + `memory_digest` 绑定；改读 Pin |
| `PreferenceLearner.direction`（`draft` / `suggest_skip`，经 direction 门禁问本人） | Matching 上下文 + Human Signal | `suggest_skip` 仍只是建议；本人回答写 Human Signals |
| `PreferenceRule`（category ∈ jobs / greetings；scope ∈ general / role / job；condition；forbidden_phrases；source_event_ids） | `MemoryRule` | scope 扩展 industry / task；category 改为开放字符串；增加 motivation、maturity、enforcement、counterexamples |
| `PreferenceEditSet` | `MemoryChangeSet` | 增加 baseline_version、unchanged_rule_ids、unresolved_signal_ids、no_change |
| `MarkdownPreferenceStore` | Bitable Search / Greeting Memory | 一次性迁移；事实类条目分流到 Materials 待确认 |
| `message_rule_confirmations`（Confirmed Rules） | Greeting MemoryRule（`explicit` 成熟度） | 本人确认过的规则可直接 `explicit`；需保留确认原话与时间 |
| `message_diff_events` | Human Signals Observation | 只取有人类操作者证据的差异；Agent 生成内容不入 |
| `SignalInbox` / `SignalCompiler` | Human Signals + Attribution + Dream | 不迁数据（fixture），只迁“字段→偏好类”交叉校验 |
| `dynamic_rule_*`（动态变量） | **不迁入 Memory** | 见审计 §5.2 |
| `memory usage / effect / simulate` | Memory Evaluation | 版本号改为 Bitable version + hash；结果来源改为 Jobs 执行结果 |

## 5. 消费者现状

| 消费者 | 当前 Memory 来源 | 目标 |
|---|---|---|
| `jobs search-plan` | G1 Markdown（`--memory-settings`）或 G3 本地 JSON（`--search-memory`），二者可同时生效 | 只读 Bitable Search Memory，Fetch Pin，Provenance |
| `memory search-round` / `fetch-pin` | G4 Bitable | 合并进 `search-plan` 执行链 |
| `greetings generate` | G1 Markdown（`select(task="greeting")` + `direction`） | Bitable Greeting Memory + Materials |
| Matching（`jobs` 评估 / `jobs/preferences.py` 主题打分） | 本人配置主题，不读 Memory | Search Memory 适用规则作为偏好上下文 |
| Optimizer（CV）/ Profile / Interview（`conversation`） | 不读 Memory | Materials（事实）+ Greeting Memory（表达） |
| Worker send gate | 不读 Memory（`grants_send=false`） | 不变 |
