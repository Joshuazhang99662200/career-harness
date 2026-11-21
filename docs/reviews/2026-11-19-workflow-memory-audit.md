# 工作流与 Memory 改造：架构审查记录

审查日期：2026-11-19。输入为本人提供的 `CareerHarness_Codex_Implementation_Brief.md`。其中的命令、审计结论与执行约束作为设计材料逐项评估，不自动授权外部操作。本轮交付本地审查、任务单与 Agent 约定，不执行 P1–P6 功能开发。

后续对齐已纠正初版架构假设：本人选定的共享多维表格是唯一业务状态源，阶段与批准两个 Schema 联合确定动作；表内本人批准不需要第二次本地批准。漏项、回写与结果报告列入 Agent 规范及实际宿主任务正文。以[代码专项审查](2026-11-19-shared-state-code-audit.md)和当前 `AGENTS.md` / 宿主任务协议为准；下述本地/远端实现观察不授予内部数据库新的业务权威。

## 版本与覆盖

| 对象 | 本轮证据 | 限制 |
|---|---|---|
| 本地分支 | `codex/greeting-first-contact-guard` | 保留原分支 |
| 本地 HEAD | `57ba6ba0cd3dd736a7cf02e919db74045e72dd06` | 本地运行与测试以此加已有工作树为准 |
| 远端 main | `32575f37c1b56eda58dfe39a6929c3f81501f44b` | GitHub 连接器读取 branch 与 compare；远端领先 17 提交，本地没有该对象，不执行 fetch/合并 |
| 版本 | `pyproject.toml` 为 `0.4.0` | 版本相同不表示实现相同 |
| 既有工作树 | 招呼技能 6 文件、测试 3 文件已有修改 | 本轮不覆盖，也不归为本轮产物 |
| PR | 开放 #33（Draft）、#31、#14、#7、#6 | 仅核对状态、标题与 base/head；未逐个审核 patch，不合并 |

Shell 访问 GitHub 失败后，改用已连接的 GitHub 只读工具核验；没有修改 Git 配置。远端对比依据：[main](https://github.com/Joshuazhang99662200/career-harness/tree/32575f37c1b56eda58dfe39a6929c3f81501f44b)、[版本对比](https://github.com/Joshuazhang99662200/career-harness/compare/57ba6ba0cd3dd736a7cf02e919db74045e72dd06...32575f37c1b56eda58dfe39a6929c3f81501f44b)、[开放 PR](https://github.com/Joshuazhang99662200/career-harness/pulls)。

本轮是跨模块架构审查：读取契约、能力目录、首次引导、宿主任务与记忆协议，核对 MemoryService、PreferenceLearner、MarkdownPreferenceStore、MessageDiffRepository、IntakeStrategyService、审批与单次投递门禁、pipeline 时钟及动态策略保护，检查相关测试。对 candidate/jobs/outreach/applications/memory/patrol/optimizer/rules 的 76 个 Python 文件做 AST 直接依赖扫描，未发现所查的 Typer、SQLite、浏览器或平台 SDK 禁止导入。该扫描不覆盖动态导入、间接依赖或全部安全属性。

未逐行审阅全部源文件；未运行前端浏览器验收；未访问本人飞书 Base、读取私有操作者映射、安装 SDK、启动长连接、创建宿主任务或进行招聘发送。不能把这份记录称为全仓逐行安全审计或真实集成验收。

## 必须先解决的设计差异

### R1：审批规则随版本变化，表格最终值不能直接授权发送（高）

本地 `AGENTS.md` 的通知规则要求在对话登记批准；远端 main 已增加所选前端的首条招呼例外，经 `console materials/decide --panel` 写入私有 SQLite 才生效，仍拒绝文字或 revision 不一致及宿主代写决定。附件简历和猎聘投递仍未接通该例外。

初版曾据此要求表内决定先形成另一条本地批准，此结论已撤回。应联合 `处理进度 × 批准状态` 消费共享环境内本人的决定，绑定当时正文、附件与版本，保留原服务内容校验和查重保护。缺适配器应列为代码缺口，不能用本地缺 approval 否认真实决定。不能伪造本人操作或批准历史，也不能把尚未整合的远端代码写成本地已实现。

### R2：无回复时长当前是固定消费者，动态配置尚不能任意生效（高）

`src/jobagent/jobs/pipeline.py` 的 `SILENCE_LIMIT` 固定为 48 小时；`src/jobagent/rules/pipeline_policy.py` 将 `ABANDON_HOURS` 与该值做兼容性比对，storage 在生产事务内执行保护。不兼容时报 `not_integrated`，这项保护应保留。

因此不能写成“用户设置任意时长即已生效”。后续需给新联系轮次绑定已确认策略版本，将时长显式传入同一 deadline/observe 路径，并保留旧记录语义；涉及其他生产参数仍独立核对兼容性。当前宿主 memory 文档也有固定时长文字，需随实际消费者一起修订。

### R3：统一 Memory P1 与 Greeting 学习已部分闭环，不能重建（中）

`MemoryService.compile` 不调用模型；`context` 仅支持 search/greeting，resume/reply 返回 `not_integrated`，来源摘要变化会阻塞。`PreferenceLearner.update/select`、`refresh_preference_memory` 和 `greetings generate` 已完成招呼偏好更新、选择和来源绑定，`tests/memory/test_memory_loop.py` 有合成闭环；能力目录还包括 usage/effect/simulate。

缺口是飞书输入归因、独立 Dream 编排、Search 真实查询消费及 CV 消费。不能用“统一 Memory 无实际消费”抹去已落地的招呼路径；usage 的账本计数也不能证明所有任务都已消费或存在因果提升。

### R4：调度需要新契约，旧巡检窗口不具备统一语义（中）

`schemas/configuration.py` 管初始化与只读准备；`schemas/patrol.py` 的窗口按上海时间解释，并有旧节奏字段。仓库搜索未找到 `AutomationPlan`、`HostScheduleReceipt` 或完整通用 Scheduler。不要借旧巡检契约为新工作流生成默认时区/周期，也不要把 `rules evaluate` 当任务已创建。

### R5：外部事件、持久队列和真实 Schema 尚未核验（中）

本地没有检索到 Bitable record changed 的事件接入或 `search_run_completed` 协议实现。简报关于 CLI 历史 API、事件字段、SDK 版本及回调时限均是待核验输入，本轮没有以官方最新文档或真实 Schema 验证，不将其写成实现事实。

事件摄取必须隔离操作者身份与偏好学习；缺少可靠 before/after、岗位身份或上下文时只存 Trace。入库完成屏障必须处理部分轮次、迟到记录及崩溃恢复，不能只依赖一个无覆盖清单的 completed 字符串。

### R6：质量门禁与远端集成需先过关（中）

本地不存在 `.github/workflows`。新增离线 CI 应尽早提供门禁，覆盖后续每阶段，不能等真实接入完才补。公开 CI 仅合成样例，不需要个人凭证。远端有 17 个尚未整合的提交，配置选项、首次引导、面板与审批契约有变，实施起点须先固定，避免重复设计。

### R7：旧状态桥接的只读 SQLite URI 未编码路径（高）

`src/jobagent/bridge/status.py:18` 直接将路径拼为 `file:{database}?mode=ro`。本环境临时目录含 URI 特殊字符；使用合成 `hash#case.sqlite3` 可稳定复现 `unable to open database file`，同一文件通过 `Path.resolve().as_uri()` 编码后正常打开。MCP 返回 isError 文本，上层测试未检查错误标志就解析 JSON，形成二次 JSONDecodeError。

`tests/bridge/test_mcp_server.py::test_pending_approvals_lists_questions_that_have_no_answer_yet` 是全量 fail-fast 首个失败。改用不含该字符的仓库私有临时目录运行原文件，6 项通过，支持路径 URI 处理为根因；不表示源代码已修复。本轮不修改生产代码，T0 中补路径回归与最小修复。

### R8：旧状态投影将 SQL 查询失败转换为空列表（高）

`src/jobagent/bridge/status.py:21–25` 的 `_rows` 捕获所有 `sqlite3.Error` 并返回 `[]`。其 `status_today` 消费方据空列表计算零计数，会将查询失败混同为成功零结果。只读状态被用于轮前检查时可能遗漏待审批或待核查项。

后续需区分缺表/旧版本兼容与真正查询失败，返回 unavailable/unknown 及来源诊断；增加读取失败不显示成功零结果的测试。此发现来自代码路径审阅，本轮未对真实业务数据库注入错误。

## 验证回执

- `python -m ruff check .`：通过。
- `python -m mypy src/jobagent`：通过，275 个源文件。
- 既有已修改测试文件专项：39 passed；这只能说明该专项结果。
- 全量 `python -m pytest -q` 已观察到失败，运行到约 24% 后停止继续收集；未取得全套统计，不能报告全量通过。重复的全量基线采集也已中止。
- `python -m pytest -q -x --tb=short`：退出 1，176 passed、1 failed，首个失败为上述 MCP 路径问题（108.41 秒）。
- `python -m pytest -q tests/bridge/test_mcp_server.py --basetemp .jobagent/review-20261119-mcp --tb=short`：6 passed（5.74 秒）。这只是隔离根因的专项结果，不替代默认路径的修复与完整门禁。
- `python -m pytest -q tests/test_documentation_contract.py tests/test_skill_context.py tests/test_capability_status.py --basetemp .jobagent/review-20261119-docs --tb=short`：23 passed（6.66 秒）。
- 本轮四份 Markdown 的本地链接检查通过；`git diff --check` 退出 0。未跟踪的新文件另做行尾空白检查。
- 基线未绿前不进入功能实施；上述通过项目不替代全量门禁。

## 处理结论

按[任务单](../workflow-memory-implementation-plan-2026-11-19.md)执行：先消除基线和版本阻碍，补共享来源与联合状态适配，再做调度契约、事件摄取、Diff/Dream、真实消费者和到期策略；CI 提前。共享环境保有唯一业务权威，候选人事实确认、本人批准及准确材料保护继续成立，不增加第二套业务状态或自动代批路径。
