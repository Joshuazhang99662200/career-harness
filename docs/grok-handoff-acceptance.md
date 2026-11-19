# Grok 交接验收（Memory Signal v1）

固定起点是 `fe5394b1b2301343bb8401783ef7bde5dcb3bbb0`。本文件只记录这一轮 Grok 能诚实填写的结论。每条都标明证据种类：静态源码审计、Mock/Fixture 测试、宿主回报、本轮独立 pytest。这里没有真实 Bitable 调用，没有把 Muse 的实机结果写成 Grok 复跑，也没有把 PR 描述里的 2064 passed 当作本轮证据。

## 1. 固定版本与分支

| 项 | 值 | 证据 |
|---|---|---|
| 仓库 | `Joshuazhang99662200/career-harness` | 本机 `git remote` |
| 起点提交 | `fe5394b1b2301343bb8401783ef7bde5dcb3bbb0` | 接手时 `HEAD` 即该提交，工作树干净 |
| 对比基线 | `main@32575f37c1b56eda58dfe39a6929c3f81501f44b` | 该提交的父提交；PR #34 页面显示 1 commit ahead / 0 behind |
| PR #34 | Draft / Open，head 仍是上述 SHA，`mergeable: true`，`mergeable_state: clean`，20 files，+1517/−13 | 本轮开始时的 GitHub 读取。本轮没有推送、变基或改写 `codex/feishu-shared-source-acceptance` |
| 本轮分支 | `cursor/memory-signal-v1-56d5` | 从上述 SHA 新建，与 PR #34 分支无关 |

PR #34 正文里的「2064 passed、2 skipped」是该 PR 的历史声明，不是本轮独立测试。

## 2. Muse 第一、二阶段（宿主回报，本轮未复跑）

以下全部是交接文档中的 Muse 实机回报，本轮没有飞书凭证，也没有复跑：

- 只读：`jobagent feishu schema` 岗位表 20 字段；生成侧查询 2 条、`has_more=true`、表版本 `rev 1476`；执行侧「已批准 + 招呼语初稿」0 条、`has_more=false`、同一表版本；单条记录 `86040431` 返回映射内容与 `mapped_content_sha256`。
- 合成记录双向回写：`reczz28bUekvoBoVO` / `CH_INTEGRATION_TEST_20261119_2c39a332`。只改已授权的「内容」字段。摘要依次为 `sha256:2c39fc26…`、`sha256:5cca8abb…`、`sha256:e6a42832…`。真实岗位、批准状态、处理进度未改。
- 原生历史：写前 create rev 148、update rev 149/150，操作者显示名 `用户979509`，不能区分人类与 Agent。生成侧写入出现在 rev 151，操作者显示为 `用户979509的飞书 CLI`。执行侧正向回读已通过；Muse 约一分钟后仍只看到 4 条历史，rev 152 尚未出现。交接要求不得为等历史而再次写入。

这些句子的证据种类是「Muse 宿主回报」。

## 3. pytest

Muse 后台 pytest 的最终日志不在这台机器上。`/tmp`、工作区和家目录都没有那次 `2064 passed` 或 basetemp 收尾日志。交接里两次 `/tmp` 磁盘满导致的失败不记成代码回归。协调说明也指出 Windows 本机在离线前没有找到最终日志。

本轮在固定提交上、新测试尚未被收集时独立跑过一次：

```text
python3 -m pytest -q --basetemp=/workspace/.pytest-basetemp
2063 passed, 3 skipped in 146.40s
EXIT:0
```

这不是 PR 正文的 2064/2，也不是 Muse 的数字。少 1 个通过、多 1 个跳过，和这台 Linux 环境有关，不能倒推成 fe5394b 的代码失败。包含本轮新增测试的完整结果见文末「本轮门禁」。固定提交上的收集总数是 2066（通过 + 跳过）。PR 正文的 2064 + 2 与本轮 2063 + 3 相差一条环境跳过，不是另一套测试。

`ruff`、`mypy`（283 个源文件，含本轮新增模块）和 `git diff --check` 的结果也写在文末。fe5394b 的 PR 正文写的是 278 个源文件，那是改动前的数量。

## 4. rev 152

本轮没有复读合成记录历史。飞书 MCP 处于未认证，环境里没有私有 FeishuConfig，也没有 Lark CLI。按交接要求，没有为了等 rev 152 再次写入 `reczz28bUekvoBoVO`。

结论：rev 152 是否已经出现，本轮状态是 **blocked**。Muse 当时看到的延迟仍然只是宿主回报。

## 5. 调用链审计

证据种类：静态源码审计（读 `fe5394b` 上的实现，本轮没有改这些读取路径）。状态词只用 implemented / partially_wired / not_integrated / host_delegated / blocked。

### 飞书网关

| 能力 | 位置 | 调用链 | 测试 | 状态 |
|---|---|---|---|---|
| schema | `FeishuGateway.schema` | `cli/feishu.py schema` → `+field-list` 分页 → 对照配置里的 field id | `tests/bridge/test_feishu_gateway.py`、`tests/cli/test_feishu.py` | implemented（适配器）。本轮没有打真实表 |
| query | `FeishuGateway.query` | 先 `schema`，再 `+record-list`；续页核对 `expected_table_revision` | 同上 | implemented（适配器） |
| get | `FeishuGateway.get` | `+record-get` → `_page`，要求映射字段齐全 | 同上 | implemented（适配器） |
| patch + 正向回读 | `FeishuGateway.patch` | 角色白名单 → `get` 比对 digest → `+record-batch-update` → 再 `get`。并发保证是 `pre_read_only` | 同上 | implemented（适配器） |
| 原生历史 | 无 | `feishu_gateway.py` 没有 history 方法 | 无 | not_integrated |

网关不持有第二套业务账本，也不授予发送权。`grants_execution_permission` 固定为 false。

### Worker 与 SQLite 业务状态

这些模块没有删除。Worker 的发送决定不再读本地批准；其余路径按下面三类保留。

- **原先重复的业务状态：** `SqliteOutreachRepository` 的 approval / ask 不再决定 Worker 能不能发。当前共享记录的批准和处理进度才决定。本地 batch 只提供待执行的招呼正文。
- **技术状态：** `SqliteWorkerRepository` 的 claim、fetch receipt、worker event，以及站点租约、日上限和间隔。这些不是批准账本。
- **兼容层：** `panel_decisions.asked_items` 仍 `SELECT ask_json FROM outreach_asks`，`record_panel_decision` 仍写本地面板决定。本地模式还要这条路径；它不能否认飞书里已经存在的本人批准，也还没接到共享表。

| 读取点 | 分类 | 调用链与现状 |
|---|---|---|
| `WorkerGateway._next` / `claim_greeting` / `authorize_greeting` / `record_greeting` | 业务决定已改到当前共享记录；执行租约仍在本地 | 每次先 `SharedJobReader.current`，再 `current_work_decision`。不再读 `get_approval` / `get_ask`。Mock 测试见下节。真实表未读 |
| `panel_decisions.asked_items`、`_approval` | 本地兼容层 | 仍读 `outreach_asks`。本地面板路径保留，没有接到共享表。not_integrated |
| `PipelineProofResolver._greeting` | 技术证明 | 仍用本地发送审计核对已发生的回读，不决定能不能发。not_integrated |
| `SqliteWorkerRepository` | 技术状态 | claim、fetch receipt、worker event。保留 |
| `PipelineRepository` / `pipeline_jobs` | 本地 pipeline 状态 | 不复制飞书「处理进度」。48 小时规则仍走既有 `ABANDON_HOURS`，本轮没有新到期账，也不会改批准字段 |
| `console/outreach.py`、`console/execution.py`、`bridge/greeting_context.py`、`cli/outreach.py`、`storage/feedback_repository.py`、`storage/pipeline_service.py`、`storage/pipeline_recontact.py`、`cli/tracking.py`、`bridge/roleplay.py`、`bridge/status.py`、`memory/usage.py` | 兼容层或其他本地读者 | 仍读写本地 `OutreachApproval` / `OutreachAsk`。它们不是 Worker 发送决定。本轮没有改成第二套业务账，也没有删掉 |

`memory send-gate` 的 `shared_send_decision` 仍是信号路径：即使批准值匹配也 `allowed=false`、`send_dispatched=false`。Worker 用的是另一次当前读取上的 `current_work_decision`。

## 5A. Worker 发送决定改读当前共享状态

证据种类：静态源码审计 + Mock/Fixture。不是真实 Bitable，也不是宿主实测。

`claim_greeting`、`authorize_greeting`、`record_greeting` 在领取、授权和回读之前都重新调用 `SharedJobReader.current`。没有 reader、记录号或显式政策时直接 `ApprovalRequiredError`，不会退回 SQLite 批准。

`current_work_decision` 只解释刚读到的 `approval` 与 `progress`（单选一项或一段文本；其他形状视为缺失）。两者都落在调用方传入的 `approved_values` 和 `ready_progress` 里，业务上才是 `ready`。招呼语正文必须和执行条目逐字相同。GPT 已经写好招呼、或本地 `outreach_approvals` 里有一行，都不能单独放行。

允许之后才使用本地批次正文、职位新鲜度、站点租约、日上限和间隔。这些是执行器状态。观察到的批准对象只在内存里交给节奏函数，不写入 `outreach_approvals`。通道记为 `shared_table`。

`decision.send_dispatched` 恒为 false。本模块不调用招聘平台。本地 claim 只是执行租约。

测试（fixture）：

| 测试 | 结果 |
|---|---|
| `test_leftover_sqlite_approval_does_not_send_when_the_table_is_unapproved` | 本地已有批准行，当前记录未批准：不领取，`reason=unapproved`，`send_dispatched=false` |
| `test_missing_or_unready_progress_does_not_send` | 进度缺失或不在就绪列表：不领取 |
| `test_current_shared_approval_does_not_require_a_local_approval_row` | 当前记录就绪且没有本地批准行：可以领取执行条目，不写批准行 |
| `test_gateway_get_is_reread_before_authorize` | 合成 `FeishuGateway.get` 在授权前再次读取；批准改成 WAIT 后授权失败 |
| `test_a_generated_greeting_is_not_approval` | 已有招呼文本但批准不是允许值：不发送 |
| `test_cli_fixture_refuses_sqlite_approval_until_the_file_is_current` | CLI 每次重读 fixture 文件。文件未批准时拒绝；改成当前就绪后才领取 |

`--feishu-config` 会走现有 `FeishuGateway.get`。本环境没有凭证，测试没有走这条活路径。状态：Worker 发送决定对 fixture / 注入的 gateway 读取是 **implemented**；真实飞书当前态是 **blocked**（无凭证，未读未写）。

### 事件订阅与原生历史

官方事件文档（本轮网页读取，不是本机 CLI 实测）确认事件名为 `drive.file.bitable_record_changed_v1`，schema `2.0`。本轮实际使用的字段只有文档里的这些：

- `header.event_id`、`header.event_type`、`header.create_time`（毫秒字符串）
- `event.file_type`、`event.table_id`、`event.revision`、`event.update_time`（秒，整数）
- `event.operator_id.open_id` / `union_id` / `user_id`
- `event.action_list[].record_id`、`action`、`before_value`、`after_value`
- `before_value[]` / `after_value[]` 的 `field_id` 与 `field_value`（官方类型是字符串）

`operator_id` 没有显示名，也没有 bot 标记。Muse 在原生历史里看到的 `用户979509` 和 `用户979509的飞书 CLI` 属于另一条历史接口，不能当成这个事件的字段。`field_identity_value` 只在人员字段出现，本轮忽略，不用里面的名字推断操作者。

官方 Node 示例是 `WSClient.start({ eventDispatcher: new EventDispatcher({}).register({ "drive.file.bitable_record_changed_v1": handler }) })`。本仓库没有加入该 SDK，没有打开长连接，没有启用生产订阅。Lark CLI 1.0.100 的 26 项事件目录是 Muse 宿主回报；这台机器没有 `lark` / `lark-cli`，本轮没有复测那份目录。

状态：fixture 接收 **implemented**；生产订阅 **blocked**（未授权，且不能假定 CLI 支持该事件）；历史读取 **not_integrated**。

### 旧记忆路径

| 路径 | 调用链 | 状态 |
|---|---|---|
| GPT Dream | `src/jobagent` 没有 dream 入口，也没有 `memory dream` 命令 | not_integrated |
| `MemoryService.compile` | `cli/memory.py compile_snapshot` → 读来源、写元数据快照。不调用模型 | implemented（快照）。该快照没有搜索消费者：not_integrated |
| `learn_search` | `cli/jobs.py learn_search_command` 把结果打印出来；`search_learning.py` 内部用假设更新词表。`jobs search-plan` 不读 `LearnedSearchPlan` | 命令 implemented；下一轮搜索消费 not_integrated |
| `PreferenceLearner.select(task="search")` | `jobs search-plan` 仅在传入 `--memory-settings` 时调用，并用返回的 `search_queries` 替换检索词。依赖私有 `memory_path` 和模型提供方 | partially_wired。本轮没有调用该模型 |

## 6. 本轮实现的 Memory Signal v1

只做三字段人工信号、归因校验和下一轮搜索参数。没有第二个 Bot、权限网关、全局 Checkpoint、本地业务账本或新业务表。`--receipt` 只保存 `event_id → payload digest`，`--learned` 只保存已发布记忆；两者都不是岗位批准或处理进度的第二套账。

### 过滤

`SignalInbox.receive`（`src/jobagent/memory/signal.py`）：

1. 只接受 `schema = 2.0` 且 `event_type = drive.file.bitable_record_changed_v1`。
2. 只保留配置中的三枚 field id：匹配档位、处理进度、招呼语。其他 field id 进入 `ignored_field_ids`。表 id 不匹配则不产生信号。
3. 记录 `record_id`、`operator_id` 的 open_id/union_id、`before_value`/`after_value` 的原始 `field_value`、`event_id`、`create_time`、`update_time`。
4. 操作者只对照显式名单。在 bot 名单里则排除，不进入 `human_signals`。名单里没有、id 缺失，或同时命中两边，都是 `unknown`，不猜成人类。
5. `before_value` 或 `after_value` 缺失、不是字符串，或该字段只出现在一侧：`value_state = unknown`，不学习。
6. 只有人类、`record_edited`、两侧值都在且不相同，才成为 `HumanFeedbackSignal`。
7. 同一 `event_id` 同一摘要再次接收：`duplicate = true`，不新学。同一 id 不同内容直接拒绝。

分类固定为：

- 匹配档位 → `Matching Preference / Calibration`
- 招呼语 → `Greeting Preference`
- 处理进度 → `Workflow / Operational Preference`

处理进度不能带搜索词。模型若对进度字段返回 search 草稿，`accept_attribution` 拒绝。

### 关联与归因

`build_request` 用 `record_id` 取 `JobSignalContext`：JD 原文、此前生成的招呼、岗位 id、方向。找不到上下文就记 `unassociated_signal_ids`，不编造 JD。

`SignalCompiler.compile` 把这个请求交给归因端口。测试里的 `RecordingAttributor` 是 fixture，不是在线 GPT。CLI `memory signal-compile` 只读取宿主已经写好的归因 JSON（`FileAttributor`），自己不调用模型。校验要求归因回显本次 `jd_digest`、原稿摘要和 `input_digest`。对不上就拒绝。

允许的记忆种类：

- 匹配档位：必须有 matching；可以另有 search（关键词、方向或排除项至少一项，并带原因）
- 招呼语：只能有 greeting，不能带搜索参数
- 处理进度：只能有 workflow，不能带搜索参数

重复的 `signal_id` 直接返回已发布记忆，不再调用归因。

这不是 Dream。Dream 仍是 **not_integrated**。本路径是 **implemented** 的 fixture/宿主归因校验。

### 下一轮搜索参数

`apply_search_memory` 只消费 `kind = search` 的记忆：追加关键词和方向，记录排除项，并从关键词里去掉与排除项完全相同的词。每一项变更带 `memory_id`、`source_event_id` 和原因。greeting / workflow 记忆放进 `ignored_memory_ids`。

`jobs search-plan --search-memory` 在原有检索词上调用这个函数，再把得到的关键词交给既有 `plan_searches`。不传该参数时，`search-plan` 的输出与原来相同。`--memory-settings` 那条 `PreferenceLearner.select(task="search")` 路径没有改掉，也没有在本轮被执行。

因此：搜索参数消费对「显式传入已发布 search 记忆」是 **implemented**（Mock 证明检索词和 `plan_searches` 的 chosen 会变）。它不会自己去招聘网站搜索，真实寻源仍是 **host_delegated**。

## 7. Mock 测试

文件：`tests/memory/test_memory_signal.py`，fixture：`tests/memory/fixtures/drive_file_bitable_record_changed_v1.json`。没有真实 Bitable。

| 要求 | 测试 | 结果 |
|---|---|---|
| 人类把匹配档位从 B 改为 A | `test_human_changes_match_grade_from_b_to_a` | 信号 preference 为 Matching Preference / Calibration，前后值为 B/A |
| 人类改招呼语 | `test_human_edits_greeting` | Greeting Preference |
| 人类改处理进度 | `test_human_edits_progress_as_workflow_not_search` | 只产生 workflow，搜索关键词不变 |
| Bot 写入不是人工信号 | `test_bot_write_is_not_a_human_signal` | `human_signals` 为空 |
| 重复事件不学习两次 | `test_duplicate_event_is_not_learned_twice` | 归因只调用一次 |
| 缺操作者或前后值 | `test_missing_operator_or_before_after_is_unknown` | `operator_kind` 或 `value_state` 为 unknown |
| 未登记的操作者 | `test_unrecognized_operator_is_unknown_rather_than_human` | unknown，不学 |
| 关联到正确 JD 和原稿 | `test_gpt_associates_the_record_jd_and_original_greeting` | 请求中的 JD、原稿摘要与另一条岗位不同 |
| 产出三类记忆 | `test_gpt_publishes_search_matching_and_greeting_memory` | search、matching、greeting；workflow 另存且不带关键词 |
| 下一轮参数实际变化 | `test_next_round_consumer_changes_search_parameters`、`test_jobs_search_plan_uses_published_search_memory` | 关键词变为 `backend engineer` + `data platform`，去掉 `retail floor`；`plan_searches` / `jobs search-plan` 的 chosen 随之变化，原因写明档位升到 A |
| 未批准不发送 | `test_unapproved_job_does_not_trigger_send`、CLI `send-gate` | `unapproved`，`send_dispatched` 为 false。批准值即使匹配，该路径也不发送 |

CLI 闭环在 `test_cli_fixture_updates_search_parameters_without_sending`：`signal-receive` → `signal-compile` → `apply-search` → `send-gate`，再次接收同一事件为 duplicate，再次编译不增加记忆。

## 8. 未接通项与最小下一步

1. Worker 的发送决定已改读当前共享记录，但 `panel_decisions`、控制台、pipeline proof 和其他本地 `OutreachApproval` 读者仍是兼容层或技术证明。真实飞书读取仍因没有凭证而 blocked。下一步只在有凭证时用 `--feishu-config` 做一次只读 `get`，不要写表。
2. 生产事件订阅仍关闭。要接时用官方 SDK 的 `WSClient` / `EventDispatcher`，先在授权的测试应用上验证，不要用 CLI 事件目录的空缺代替实测，也不要在本仓库里直接 `start()`。
3. 原生历史读取仍缺适配器方法。rev 152 需要有凭证的只读查询，不能靠再写一次合成记录来等它出现。
4. Dream 仍未接通。现在的编译器只校验宿主交来的归因。真正调用 GPT 之前，要单独做无增量跳过、版本和失败不推进游标；本轮故意没有做这套。
5. `learn_search` 和 `MemoryService.compile` 的产物仍然没有被新的搜索消费路径读取。新的消费入口是 `jobs search-plan --search-memory`。
6. 真实寻源、发送、代聊都没有接上，也不在本轮范围内。

## 9. 本轮没有真实外联

本轮没有发送招聘消息，没有投递简历，没有代聊，没有修改真实或合成 Bitable 记录，没有新建 Bitable 记录，没有改匹配档位、匹配理由、招呼语、批准状态或处理进度，没有启用生产事件订阅，没有输出 API key、token、cookie 或私有 FeishuConfig。`reczz28bUekvoBoVO` 没有再次写入。

## 本轮门禁

在 `cursor/memory-signal-v1-56d5` 上独立执行，包含本轮新增测试。证据种类：本轮 pytest / ruff / mypy，不是 Muse 复跑。

```text
python3 -m pytest -q -rs --basetemp=/workspace/.pytest-final
2086 passed, 3 skipped, 0 failed in 162.54s
EXIT:0
```

3 个跳过都在 `tests/reasoning/test_output_schemas.py:38`：`No module named 'anthropic'`。本环境没有安装可选的 `reasoning` extra。

这条命令包含 Memory Signal v1 和 Worker 共享状态测试。固定提交上、那些测试尚未收集时，本机基线是 2063 passed / 3 skipped，退出码 0。不要把它和 PR #34 的历史数字混用。

```text
python3 -m ruff check .
python3 -m mypy src/jobagent
git diff --check
```

三条都是退出码 0。`mypy` 检查 283 个源文件。`ruff check .` 在删除临时 pytest 目录后执行，那些目录不入库。
