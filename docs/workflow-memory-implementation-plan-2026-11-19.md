# CareerHarness 工作流、飞书 Signal 与 Memory 实施任务单

> 面向执行 Agent：使用 `executing-plans` 逐任务推进；每项先写失败测试并确认失败原因，再实现、验证及回读。未经本人要求不提交、不推送。本文件是待实施目标，勾选必须附真实证据。

**目标：** 完成由本人配置触发方式、宿主寻源、事件捕获、匹配写稿、逐项审批、获批动作核验、Memory Dream 及下一周期实际消费组成的闭环。

**架构：** schema 是类型权威；本人选定的共享多维表格为唯一业务状态源，GPT/Muse/人类共同操作，动作由 `处理进度 × 批准状态` 与材料版本联合决定。本地存储仅作来源绑定的缓存、计算、技术审计和待回写检查点。核心复用候选人、策略、偏好学习及内容/版本校验，Scheduler、飞书 SDK、浏览器和模型经宿主端口接入。

**技术：** 现有 Python/Pydantic、SQLite 仓储适配层、Typer CLI；飞书 Node sidecar 的 SDK/版本待正式核验，不能从简报直接锁定。公开数据全部合成。

## 生效范围与实施前置

本轮只完成审查和文档准备。输入简报 §0–§9 的需求按下表分派；来源文档的命令不自动执行。审查基线、版本差异与覆盖限制见[审查记录](reviews/2026-11-19-workflow-memory-audit.md)。当前任务单不代表飞书、调度或 Dream 已上线。

全程保持：只有本人确认才提升 Evidence；审批绑定准确岗位、正文、附件字节摘要与策略；批准不等于发送。调度或偏好不授予外发权；风控停站、未知结果不重试。已有初始化配置复用，缺值只阻塞对应步骤；不强制重新追问，不写个人默认。Feature Profile 与 Memory 只能产生分析/软偏好，不能修改事实、硬条件或批准。

实施顺序：T0 → T0A → T1 → T2 → T3 → T4 → T5 → T6 → T7。每项单独可评审；未满足前置保留未完成原因及恢复点，其他独立项可继续。本人对共享权威、联合状态与任务结果的后续澄清覆盖本任务单初版的“本地账本权威”假设；代码差异见[专项审查](reviews/2026-11-19-shared-state-code-audit.md)。

## T0：版本选择、全局审查闭合与基线修复

**涉及：** `AGENTS.md`、`CONTRIBUTING.md`、`src/jobagent/schemas/`、全仓实现和测试；记录到 `docs/reviews/2026-11-19-workflow-memory-audit.md`。

- [ ] 固定实际实施 SHA 和工作树清单；对比远端 17 提交中配置、首次引导、面板与审批变化。保留当前 9 个已修改文件；不得自动 merge、cherry-pick、reset 或切分支。
- [ ] 按 candidate → jobs/intake → optimizer → outreach/applications → conversations/pipeline → memory/rules → storage/harness → CLI/MCP/console → frontend 顺序闭合审查，逐模块保存路径、发现、复现测试与未覆盖项；没有发现时报告审查范围，不宣布无风险。
- [ ] 定位全量基线失败；区分现有代码、工作树、环境与版本因素。先以精确用例复现，再修复根因或给出可验证隔离；不得删测试、放松审批或把失败改为 skip 来过关。
- [ ] 为 `bridge/status.py` 增加 URI 特殊字符路径的失败回归，用文件 URI 编码修复只读连接，再跑默认临时目录下的 MCP 测试。另写 SQL 读取失败不被显示为零结果的回归，保留明确的 unavailable/unknown 诊断；不能只修改测试临时路径掩盖产品缺陷。
- [ ] 回读远端当前开放 PR 的实际变更范围及依赖；选择实施版本属于显式集成步骤，本任务单不授权合并。
- [ ] 依次运行 pytest、Ruff、mypy、diff 检查，记录命令、版本、数量、失败与退出码。基线未绿时先处理相关失败，再改生产代码。

**输出/验收：** 已固定实施版本、全部模块的覆盖表及问题清单，必要修复有先红后绿证据。仅静态扫描或部分测试不勾选本项。

## T0A：共享状态来源、联合映射与结果闭环

**已核实缺口：** `WorkerGateway._batch`、`panel_decisions.asked_items`、`PipelineProofResolver._greeting` 均依赖本地问题或批准记录；PipelineJob 没有直接表达飞书联合状态；HostRoundReporter 不检查共享回写。这里不预设这些本地入口就是 Muse 当前实际执行路径。

**计划新建：** `src/jobagent/schemas/shared_business.py`、`src/jobagent/bridge/shared_business.py`、`tests/bridge/test_shared_business.py`。**复用或修改：** `schemas/worker.py`、`bridge/worker.py`、`storage/pipeline_proofs.py`、`schemas/host_checks.py`、`storage/host_reports.py` 及相应测试。新增结构放 schemas，适配器不复制类型定义。

- [ ] 在 `SharedBusinessSnapshot` 绑定来源范围、record_id、字段 Schema 版本、实际读取版本/时间、两个状态值、材料引用/摘要和原始本人决定证据；快照不拥有独立业务裁决权，写前必须复读共享状态。
- [ ] 对照实际阶段和批准字段 Schema 及既有业务协议实现 `SharedActionResolution`：确定动作、等待/无需动作/终态或具体冲突；穷举阶段与批准组合，并覆盖空值、未知选项、旧 Schema。不能向本人重复询问两个字段已定义的动作，也不能自行把旧批准扩展到新阶段材料。
- [ ] 为原始本人批准建立来源验证接口，保留操作者、时间、历史版本与对应材料；适配原门禁的精确摘要和查重保护，本地缺 ask/approval 行不能要求重复批准。既有本地模式在显式选择时保留，不从缺记录静默回退或删门禁。
- [ ] 为 `SharedActionReceipt` 分开记录动作事实、业务回写与回读证据；通过共享环境既有记录协议保存，不在新库中建立第二套业务当前态。并发编辑拒绝陈旧覆盖，事件重放不重复动作。
- [ ] 外部动作完成后回写失败，持久待回写检查点并显式报告；恢复先核验平台与共享记录，再补回执，不能重发。Base 不可用也必须给当前对话/已授权报告通道结果，未送达保留待报告。
- [ ] 生成本轮覆盖清单，对每条输入核验完成、无需动作、等待、受阻、失败或结果不明的去向与证据；不能仅检查总数。共享阶段、材料或批准变化重读后处理，分页未完成和迟到项保留恢复点。
- [ ] 失败测试覆盖“表内本人已批且本地无批准仍可被正确消费”、AI 代批拒绝、正文/附件变更、已完成不重做、终态不重开、两个 Agent 竞争、陈旧覆盖、回写失败恢复不重发、遗漏一项不得宣称覆盖完成。现有 `core_checks_passed` 保持范围说明，另以实际共享回写证据判断业务闭环。

**输出/验收：** 新类型与适配器在合成测试中消费同一共享来源、复用原门禁、逐项回写和核验；真实 Schema/宿主链未验收前标未接通。Agent 与任务正文明确任务结果，不凭文档修订宣称已部署。

## T1：尽早加入离线 CI

**新建：** `.github/workflows/ci.yml`。**参考：** `pyproject.toml`、`CONTRIBUTING.md`。

- [ ] 选择仓库支持的 Python 3.11，配置 push/pull_request，最小 `contents: read`；安装 `.[dev]` 后执行四条门禁，不传个人密钥。
- [ ] 先用本地命令验证相同环境；公开 CI 使用 fixture/mock，不能访问招聘账号或本人 Base。新增 Node 测试脚本时再把相应 job 接入。
- [ ] 真实 Actions 结果仅在明确发布授权后的实际 run 上核验；本地通过与 workflow 文件存在分别报告，不虚构运行 ID。

**输出/验收：** CI 配置可解析，四条门禁本地通过；远端运行未发生时标为未验收。

## T2：首次 Automation Setup 与宿主回执契约（简报 P1）

**先读：** `schemas/configuration.py`、`schemas/dynamic_rules.py`、`schemas/patrol.py`、`rules/preparation.py`、`storage/configuration_repository.py`。

**计划新建：** `src/jobagent/schemas/automation.py`、`src/jobagent/automation/ports.py`、`src/jobagent/automation/service.py`、`src/jobagent/storage/automation_repository.py`、`tests/schemas/test_automation.py`、`tests/workflows/test_automation_setup.py`。迁移号在实施版本中取下一个空闲编号，不复用已有号。

**修改：** `skills/job-hunting/references/first-use.md`、`hosts/personal-ai/tasks.md`；若暴露 CLI，补 `src/jobagent/cli/automation.py`、命令注册与能力目录。任何拟新增入口实施前仍不可调用。

- [ ] 定义 `AutomationPlan`（candidate、rules_version、parent/version、本人提问/原话出处），`WorkflowTrigger`（workflow、mode、enabled、适用时区/窗口/间隔/额度）、`ScheduleWindow`、`HostScheduleReceipt` 和 Setup 输入输出。不同模式条件校验；manual 不强制 schedule 字段，scheduled 缺 IANA 时区或窗口拒绝，禁止静默填默认。
- [ ] 复用动态规则的候选人、版本与本人主动修改治理；计划仅引用对应预算和 `ABANDON_HOURS` 的确认版本，不复制一套可独立修改的数值权威。
- [ ] 分开配置 Search、消息/状态核查、获批材料处理、到期核查、Dream、通知；仅展示真实能力支持的选项，保留自定义。已有确认配置直接复用，首次未配置的工作流维持关闭/手动，不能阻塞已配置项。
- [ ] 端口分别提供能力探测、prepare/create/read/pause/resume/update/delete；核心只校验，不创建 OS 任务。mock 仅用于合成测试，unsupported 返回真实能力缺口。
- [ ] 写版本化私有计划与回执：创建或变更后 read 核对 task_id、plan_version、timezone、next_run_at、status；未知结果先查询，旧任务未确认前不重复创建。暂停、恢复、删任务仍需本人相应请求。
- [ ] 实际任务正文同时绑定结果契约：共享输入范围、联合状态动作、逐项产物、回写位置、业务回读、未完成项与恢复方式；设置后回读正文核对。结果规范见 `hosts/personal-ai/tasks.md`，不能仅用任务 ID/下次运行时间作为业务验收；已有任务读不到正文则标未核验，不擅自重建。
- [ ] 失败测试覆盖已有档案不重问、单项修改不动其他值、缺时间/时区、DST 缺失/重复时刻、跨午夜、非法范围、无 Scheduler、回执与计划不一致、创建结果不明及恢复。

**输出/验收：** 合成适配器证明配置保存与宿主执行分离；真实任务只在用户配置并授权创建后验收。现有 `PatrolSchedule` 不自动迁移为新计划。

## T3：飞书只读预检与原始事件耐久摄取（简报 P0/P2）

**新建适配器目录：** `hosts/feishu-event-bridge/`（独立 Node 包、README、脱敏 fixture、单元测试）；`src/jobagent/schemas/behavior.py` 定义 host-neutral Trace/Diff。Python 处理逻辑放 `src/jobagent/bridge/behavior_ingestion.py` 与私有仓储适配器。

- [ ] 真正开展飞书接入时先按现行规则运行 `lark-cli.cmd auth status --json --verify`，不展示凭证；仅明确缺授权或 scope 时走最小授权，不初始化覆盖现有配置。个人资源优先 user；机器人资源与 Muse 的 bot 配置限对应宿主适配器使用，不能全局强制 bot。
- [ ] 经当前 CLI `--help`、官方事件 Schema 与 SDK 官方文档核验表/字段/记录历史及长连接能力；简报的命令、版本与时限不作为已核实结论。只读读取已关联 Base，映射存私有区；缺映射只停止相关接入，不猜 ID、不全表扫描冒充历史审计。
- [ ] 定义 Trace：事件 ID、租户/应用范围、表/记录/字段、操作人、发生/接收时间、动作、原始 before/after、payload_digest。追加原文与处理回执分离，processed_at 不回写改变原始事实；未知保留 unknown。
- [ ] callback 只验证、去重并耐久写 spool，不运行模型、不写订阅表；成功应答前确保持久化，崩溃重启可恢复。事件 ID 在平台身份范围内唯一；同 ID 同摘要 no-op，同 ID 异内容拒绝并记录冲突。
- [ ] 私有 actor 映射核验 Human/Muse/GPT/Codex/System，不能按显示名推断；多客户端采用单实例租约/claim。worker 的处理回执、失败隔离与重放不得覆盖原事件。
- [ ] 合成 fixture 覆盖新增/编辑/删除、多字段、JSON 字符串、富文本、附件、单选、关联、公式与系统字段、未知 actor、同 ID 异内容、乱序、迟到、断电恢复和 ACK 前失败。性能门槛采用核实的平台限制。
- [ ] 历史导入只处理本人指定记录及分页范围；保留原操作者和时间，不能从最终值反造 diff。真实测试记录编辑、事件订阅或外部写入先展示方案并取得相应确认。

**输出/验收：** 无个人凭证的 sidecar 与合成耐久摄取测试；真实订阅、Schema 与事件 fixture 未验证时保留 blocked/unverified，不能标接通。Base 新增表/字段属于另行审阅的变更，不在此步自动执行。

## T4：Behavior Diff、归因与 Memory Dream（简报 P3）

**复用：** `outreach/preference_memory.py`、`bridge/preference_memory.py`、`bridge/preference_reasoning.py`、`storage/message_diff_repository.py`、`schemas/search_learning.py`。

**计划新建：** `src/jobagent/memory/dream.py`、`src/jobagent/schemas/memory_dream.py`、`src/jobagent/bridge/behavior_diff.py`、`src/jobagent/storage/memory_dream_repository.py`、`tests/memory/test_dream.py`、`tests/bridge/test_behavior_diff.py`；模型入口单独注册 `memory dream` 并更新能力目录，保持 `memory compile` 原语义。

- [ ] Diff 绑定 Trace、原始字段 Schema、准确 job/contact round、JD/material snapshot 与 before/after；上下文不足停留 Trace。grade_override 不冒充 approve/decline，文案修改不冒充岗位拒绝；AI 编辑不进入 Human Preference。
- [ ] 完整文案改写映射现有 `SourcingFeedback` 与 diff 仓储，保留 required candidate、岗位、原稿、改稿、JD、公司/职位及真实本人来源；缺任何必需信息不伪造补齐。
- [ ] Dream request 绑定候选人、期望旧版本、成功 cursor、事件 ID+摘要、快照引用、prompt/Skill 版本和 input_digest；无有效增量直接返回 skipped，不调用模型。
- [ ] 输出类型化 MemoryPatch：add/edit/merge/retire、previous_version、source_event_ids、scope、confidence、reason；验证来源、任务隔离、反例及多岗位样本，不让模型决定 actor、审批、事实确认或 cursor。单次行为只生成局部候选，明确本人指令和重复偏好分开表示。
- [ ] 以 expected_version 做并发保护，成功校验和耐久存储后提交新版本与游标；失败/乱序/并发冲突不丢事件。跨 Markdown/SQLite 无原子事务时采用先暂存、校验、提交 manifest 再激活的恢复协议，禁止先推进 cursor。
- [ ] 分别发布 search_memory、search_strategy、greeting_memory、cv_memory 的版本化投影与来源索引；沿用已有 Greeting 存储格式和校验，避免双重可变权威。云文档发布与 Registry 是宿主可选外部步骤，失败保留未发布状态，不重复学习。
- [ ] 失败测试覆盖模型异常、非法 Schema/scope、旧 digest、缺来源、同事件重放、候选人串用、三类偏好污染、并发版本与发布中断。只在原文/事件支持时形成规则，无法关联的旧历史不补造。

**输出/验收：** 可重算 Diff 与版本化 Dream，原事件不变、失败游标不前进，compile 依旧无模型。飞书 Registry 如需新增，先给出字段方案再等待本人明确批准。

## T5：搜索完成屏障与下一轮实际消费者（简报 P4）

**修改：** `schemas/job_intake.py`、`storage/intake_strategy.py`、`cli/job_intake.py`、`schemas/memory.py`、`memory/service.py`、`cli/greetings.py`、优化器 request/路由消费者和对应 tests；`hosts/personal-ai/tasks.md`、`hosts/personal-ai/memory.md`。

- [ ] 先定义 Search Run 完成清单：run_id、候选人、策略/规则/记忆版本、实际查询回执、入库 job/snapshot 列表、覆盖范围、unfinished 与恢复点；持久写入并对账后发布完成事件。同轮重放幂等，部分/失败轮次不冒充全部完成；迟到记录进入显式补充版本。
- [ ] 评估 worker 只领取已对账的清单版本，绑定 job、search_run、完整 JD 和材料版本；恢复中不重复起草或重开已联系/拒绝/关闭/未知结果岗位。匹配 grade 以现有契约为准，界面 A/B/C/D 若需映射须显式定义，不能另立类型权威。
- [ ] 搜索模型输出接入 `IntakeStrategyService` 现有 strategy/active/claim/record-search；计划只说明拟执行，实际查询必须通过预算与调用网关并绑定真实回执。验证关键词真实进入下一轮调用，不只比较生成的 Markdown。
- [ ] Greeting 保留已有 `refresh_preference_memory`、selection 和 source_binding；检查消费的是本轮冻结版本，完善外部事件溯源，不重写已成立的 usage 闭环。
- [ ] Resume 先扩展 task 隔离契约，再接入优化器 request → evidence → draft → independent review → assemble → diff；CV Memory 只影响选择与表达，任何主张仍引用已确认 Evidence。未接完整消费者前 resume 继续 `not_integrated`。
- [ ] Feature Profile 绑定事实版本、证据 ID 与推导版本，只作为分析输入；不得作为 canonical evidence 或绕过初次事实确认。
- [ ] 合成两轮测试：第一轮入库/改稿/本人反馈 → Dream → 第二轮真实服务请求消费新版本。覆盖迟到事件、预算触顶、同轮重复 claim、JD 更新导致派生失效及未完整 JD 拒绝起草；记录 input_digest、selected rules 与 artifact 引用。

**输出/验收：** Search/Greeting/CV 分别有实际请求和产物的来源证据；支持哪些任务就报告哪些。不得把一次 mock query 写成真实浏览器执行，不靠手写 usage_verified=true 验收。

## T6：审批适配、获批动作与动态到期（简报 P5）

**修改前复核：** `applications/approval.py`、`applications/delivery.py`、`bridge/panel_decisions.py`、`jobs/pipeline.py`、`rules/pipeline_policy.py`、`storage/pipeline_service.py`、`storage/pipeline_policy.py`、`tests/applications/`、`tests/storage/test_pipeline_policy.py`。

- [ ] 消费 T0A 的共享状态快照及原始本人批准，联合阶段确定当前动作；本人表内批准无需再执行一次 `console decide` 或对话审批。复用既有服务对内容、附件、目标、版本和重复动作的校验；缺共享消费能力的旧入口明确标未接通并报告，不以本地缺 approval 行否认决定，不伪造内部批准。
- [ ] 覆盖非本人/未知 actor、未经提问、原文/revision/附件变化、重复事件、撤回、旧批准迟到、已有会话、结果不明等拒绝路径。发送前再次验证摘要、目标及真实会话，未知先核验，禁止自动重发。
- [ ] 到期策略从本人当前确认配置为新联系轮次冻结版本，经现有 pipeline 单一时钟消费；复用 sent/read/last substantive/resume sent 的语义，不新建第二状态机。改变时长先写失败测试，保持事务内权威版本核对。
- [ ] 用两个不同的合成时长证明实际 deadline 随参数变化，另用 48 小时作为边界测试样例；它不成为新默认。保留旧轮次版本和旧终态，不追溯重算，不借配置变化复活 abandoned。
- [ ] 保护无真实时间、proof_pending、paused、未知页面、已有回复、interviewed 和不兼容策略；到期只生成候选，再依实际观察更新允许的状态，不改本人批准字段。
- [ ] 检查频率依本人 AutomationPlan；宿主不支持 deadline timer 时报告下一实际核查时间。处理获批积压、消息与到期后才寻源，但积压处理仍需逐项授权，调度触发不授予发送权。

**输出/验收：** 合成的批准→候选→单次 mock 动作→回读与 due/observe 链闭合，所有旧门禁回归通过。真实招聘发送不作为本轮文档任务或接通测试的默认动作。

## T7：文档、质量门禁与真实宿主分级验收（简报 P6）

**修改：** `skills/job-hunting/SKILL.md`、相关 references、能力目录、`hosts/personal-ai/README.md` / tasks / memory、适配器 README、`CHANGELOG.md`、`docs/README.md` 与 `AGENTS.md`。

- [ ] 以 implemented / host_delegated / contract_only / not_integrated 分别描述代码与宿主状态；能力目录继续使用现有中文状态及双向命令校验，不能未经迁移另换枚举。每新增 CLI 同步目录与测试。
- [ ] 每阶段记录先红后绿与四条门禁；新增 Node 包跑其单测，前端有改动时按 package.json 跑 typecheck、build 和 Playwright，不虚构不存在的 lint 脚本。公开 CI 不用真实凭证。
- [ ] 逐轮核验共享输入覆盖、联合状态消费、实际产物、回写回读与未完成项；本地核心检查通过与共享业务闭环分别报告，禁止漏写后标整轮完成。核验实际部署任务正文的结果要求，未读到或未部署分别说明。
- [ ] 输出全部源码、schema、迁移、无凭证 sidecar、无个人默认的配置样例、Dream 协议、测试与来源表；迁移仅在合成库演练，真实私有库迁移须独立核对备份、版本与恢复。
- [ ] 真实验收分层：只读 CLI/Schema；本人指定测试记录和事件；实际 Scheduler 创建/回读；两个独立周期的恢复、Dream 和真实请求消费。每层需要的权限和手工后台设置单列；未授权或能力缺失就保留 blocked，不用合成回执替代。
- [ ] 形成最终交付说明：完成范围、文件清单、测试、已知缺口、私有部署操作与手工授权要求。未明确要求不提交、不推送、不创建 PR；PR 文案准备不等于已发布。

## 门禁与恢复记录

```powershell
python -m pytest -q
python -m ruff check .
python -m mypy src/jobagent
git diff --check
```

每项完成记录：task_id、实施 SHA、输入/输出版本、测试命令与退出码、真实/合成标记、未完成原因、下一恢复点。缺授权、真实 Schema、事件样例、必要来源或宿主能力只停止对应步骤。正常业务不因本任务单重开个人配置，不自动启用飞书通知或修改已有宿主任务。

## 简报需求对应

| 简报范围 | 任务 | 验收证据 |
|---|---|---|
| §0–§1 审计与复用 | T0 | 版本/覆盖表、基线与差异处理 |
| §2.1 事实与特征 | T2、T5 | 事实授权不变，分析有溯源 |
| §2.2–§2.3 轮次与材料 | T5 | 完成清单、完整 JD、真实请求与材料版本 |
| §2.4 审批与动作 | T6 | 原门禁落库回读，字段不直接授权 |
| §2.5 / §6 到期与调度 | T2、T6 | 动态消费者与真实宿主回执 |
| §2.6 / §5 Dream | T4、T5 | 游标原子发布与下一轮消费 |
| §3 Automation Setup | T2 | 无默认、复用、逐项本人决定 |
| §4 CLI / SDK / 历史 | T3 | 官方核验、耐久摄取、指定历史范围 |
| §7 验证矩阵 | T2–T7 | 合成测试与分级真实验收分开 |
| §8 CI | T1、T7 | 提前门禁，实际 run 独立记录 |
| §9 交付 | T7 | 代码、文档、回执与明确缺口 |
