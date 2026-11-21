# 全局重构分阶段计划（轻量 Skill 化）

**日期：** 2026-11-21　**分支：** `claude/lightweight-skill-refactor`（由 PR #36 头部 `f3eb022` 切出）　**方向依据：** [轻量化架构](lightweight-skill-architecture.md)

本计划把“代码层 → 轻量 Skill + 飞书多维表格唯一状态机”的重构拆成可独立交付、可回退的阶段。它是计划，不证明任何阶段已完成；每阶段完成以该阶段的验收证据为准。

## 0. 总原则

- **能轻度设计就轻度设计。** 不另起炉灶写代码，不加防御性校验层，出错就让它报错（let it crash）；能复用现有实现、`lark-cli` 与多维表格自身能力就复用，规则优先写进角色 md 与 Skill reference。
- **先迁移后删除。** 删除任何模块前，先把它仍有价值的规则与口径迁到 Skill，并确认已无消费者。
- **两条核心主张。** GM 只用材料表中的内容写招呼语与简历、不编造经历；每次外发都要本人在 `批准状态` 填 `已批准`。材料 md 与 Memory 由 GM 维护、直接发布，不要求本人审批长文档；错误经本人驳回或修改被 trace 捕捉，由 GM 查证后写入 Memory。
- **不做生产双写。** 一次性迁移工具可以读取旧数据；生产运行时只有 Bitable 一个业务权威，读不到时报告，不静默回退到 SQLite / Markdown / JSON。
- **真实写入逐项授权。** 新增表、字段、选项、Workflow 启用等 Base 变更都先展示准确差异，经本人确认后才执行；本次重构全程不做真实招聘发送、投递或代聊。
- **验证分层报告。** Mock / 契约测试、对本人 Base 的只读验收、合成记录的真实读写、宿主实际运行，分别报告，不互相替代。

## 1. 现状基线

| 项 | 状态 |
|---|---|
| 门禁（本分支） | ruff 通过；mypy 290 个文件无问题；pytest 2153 passed / 2 skipped |
| 代码规模（PR #36） | 约 5.4 万行 Python；23 个 CLI 命令组；SQLite 39 个迁移、123 张表；53 个前端文件；229 个测试文件 |
| 保留的写作 Skill | `greeting/`、`optimizer/`、`jd-grounded-template-tailoring` 为纯 prose，不直接调用 `jobagent` 命令 |
| 写作 Skill 的代码牵连 | `greetings generate` 与首招质量否决测试；optimizer `index/*.yaml` 契约及其测试；简历 PDF 渲染（`rendering/`） |
| 文档与代码耦合 | 能力目录含 232 处 `jobagent` 命令引用；17 个测试读取 `skills/` 或 `docs/`（含 `test_capability_status`、`test_documentation_contract`、`test_skill_context`） |
| 多维表格 | 岗位、材料、Human Signals、搜索与匹配记忆、招呼语表达记忆 5 张表；3 条 Signal Workflow 保持 Disabled |

## 2. 阶段总览

| 阶段 | 目标 | 主要产物 | 前置裁定 |
|---|---|---|---|
| P1 契约 | 把新架构写成仓库规范 | 新 `AGENTS.md`、`GM.md` / `EM.md`、`bitable-contract.md`、`memory-dream.md` 增补 | **已完成**（门禁 2154 passed） |
| P2 Initial Setup | 任一宿主可按 Skill 完成接入 | `first-use.md` 改为 Initial Setup、GM 待你批准写入规则、配置示例 | **仓库部分已完成**；真实 Base 的 Bot 身份与表结构对照待本人授权 |
| P3 Skill 收敛 | Skill 树只剩新路径需要的内容 | 新 `SKILL.md` 路由、精简 references、重写能力目录 | P1 |
| P4 Signal 与 Dream | 人类 trace → Memory 闭环 | Dream 方法 reference、宿主任务定义、发布回读规则 | P2 |
| P5 旧数据迁移 | 旧偏好与事实一次性进入 Bitable | 迁移 dry-run 报告、本人确认后的写入与回读对账 | P2、P4 |
| P6 代码退役 | 删除无消费者的重型代码 | 按依赖顺序的删除提交；只留两项复用代码 | P3–P5 |
| P7 全局验收 | 端到端证明新路径可用 | 合成记录的真实读写回读、门禁、文档一致性报告 | 全部 |

## 3. 各阶段细节

### P1 契约（只改文档）

1. **改写 `AGENTS.md`。** 删去“SQLite 驱动审批”“仓库不内置飞书”“React 为同级前端”等旧段落；废止 Evidence 概念；按第 4 节裁定改写核心主张与硬性边界；写入三方角色、单一 Bot 写入、非 Bot 即人类、字段归属、轻量设计原则。
2. **新增 `skills/job-hunting/roles/GM.md` 与 `EM.md`。** 各自的读取范围、可写字段、禁止事项与交接列（`Muse处理` / `GPT处理`，D5）。GM 每看完一份 JD 评级后把 `批准状态` 写为 `待你批准`；EM 不写 `匹配档位`、`匹配理由`、`招呼语`、`简历cv（PDF）`，执行前读取最新值。
3. **Bitable 数据契约。** 五个语义域到实表的映射方式（只存语义名，不存 ID）；字段归属；回写规则沿用 `feishu-shared-source.md`。
4. **Signal / Memory 写法。** Dream 第一步丢弃 Bot 写入的 Signal 行；Observation → Motivation → Rule Formation 的归纳方法；发布沿用 PR #36 已有做法（单记录原地更新、`version + 1`），不另加校验。

**验收：** 文档门禁测试通过；契约中无个人标识与真实数值；与能力目录不矛盾。

### P2 Initial Setup 与 Bitable 访问

1. **Setup 流程 reference**（按本人确定的顺序）：检查飞书 / 钉钉 CLI 已安装且已授权，不满足即停止 → 询问角色部署（GM / EM / 兼任）→ 收集个人资料写入材料表（一份简历 + 一份 md）→ 发现 Schema 并映射五个语义域 → 本人确认 → 按平台选定 EM 执行方式（云端浏览器 / MCP / 浏览器插件），并把搜索间隔与各平台搜索数量写入私有 `settings.json` → 分立部署时建立或复用 MCP bridge。
2. **写入身份。** 私有配置登记唯一 Bot 身份；所有 Agent 写入走同一条 CLI。
3. **材料表承载个人资料**（D2）：一份简历放 `附件`，一份由 Agent 自由组织的 md 放 `准确全文`，此后只在 md 内增删改，用时读取。
4. **不启用高级权限**（D4）：GM / EM 隔离靠角色 md 与复用 PR #36 `feishu patch` 的写前字段白名单。
5. **批准 Signal**（D1）：新增或调整一条 Workflow 监听 `批准状态`，须本人确认后执行。
6. **PR #36 配置调整。** `FeishuConfig.identity` 改为 Bot；字段白名单补上“GM 对 `批准状态` 只能写 `待你批准`”。

**验收：** 对本人 Base 的只读 Schema / 分页 / 查询 / 记录历史验收；Bot 身份的合成记录写入与正向回读（须本人授权）。

### P3 Skill 收敛

1. **`SKILL.md` 改为角色路由入口**：识别当前角色 → 加载对应角色 md → 按任务按需加载 reference。
2. **保留**：`greeting/`（含首招质量门禁）、`optimizer/`、`jd-grounded-template-tailoring`、匹配档位口径、`stop-conditions.md`（改写）。全树把 Evidence 术语改称材料事实；`evidence-policy.md`、`candidate-kb.md` 退役。
3. **退役 reference**（迁出仍有价值的规则后删除）：浏览器寻源、猎聘列表、连接器契约、巡检、worker、pipeline、sent-tracking、MCP runtime、寻源预算与可靠性、harness、roleplay 评测、Muse 旧队列接入与回填、Console 相关说明。
4. **重写能力目录**，只登记新路径的能力与状态；同步 `test_capability_status` 的双向断言。

**验收：** `test_skill_context`、`test_documentation_contract`、能力目录测试通过；Skill 树可渐进加载，入口不预读全部 reference。

### P4 Signal 与 Dream

1. **启用 Signal Workflow**（须本人确认）：三条 Workflow 加监听 `批准状态` 的一条，只追加 Human Signals 行；Bot 写入的行由 Dream 丢弃。
2. **Dream 方法 reference**：GM 在本地时区凌晨读取上次成功游标后的人类 Signal，关联岗位、JD 与原始生成内容，分别生成 Search / Greeting MemoryChangeSet；无有效增量跳过模型调用。
3. **消费规则**：EM 下一轮搜索前读 Search Memory，GM 写招呼语、简历前读 Greeting Memory，并记下所用版本。Memory 是否有效看上线后的批准通过率；通过率仍低就回头重查 Memory，不加自动校验。
4. **宿主任务**：在 `hosts/personal-ai/tasks.md` 写明输入、读取域、产物、回写位置、回读验收与失败恢复；复用已确认的调度配置，读不到标记未核验，不擅自新建任务。

**验收：** 合成 Signal 的端到端 dry-run（丢弃 Bot 行、归纳、发布）；文档更新、宿主任务回读、真实运行三者分别报告。

### P5 旧数据一次性迁移

1. **个人资料**：本地 Candidate Evidence 的内容导出，由 Agent 整理进材料表的那份 md，直接作为生产来源，不要求本人逐条审阅。
2. **旧偏好**：Markdown 偏好、已确认文案规则（`message_rule_*`）、`PreferenceRule` 由 GM 整理进两份 Memory；来源或语义不明的直接丢弃，不留给本人审阅。
3. **动态变量**：查询次数、轮询时间等配置继续作为私有配置，不迁入 Memory。
4. **流程**：dry-run 输出数量、冲突与丢失字段 → 写入 → 回读核对数量；只有写入本人 Base 这一步需要本人授权，不要求本人审阅迁移内容。

**验收：** 迁移对账报告；之后生产路径不再读取旧文件。

### P6 代码退役（按依赖从外到内）

1. `frontend/` 与 `console/`、`cli/console.py`。
2. bridge 中的 MCP 服务与 `bridge/status.py` 的 SQLite 查询。
3. 无新路径消费者的 CLI 命令组（逐组核对引用）。
4. `connectors/`、`jobs/` 流水线、`patrol/`、`applications/`、`harness/` 本地账本部分。
5. 旧 Memory 实现（Markdown / JSON 存储、SignalInbox、SignalCompiler）。
6. 最后删除 `storage/` 与全部 SQLite 迁移。
7. **只保留两项代码**（D3）：写前字段白名单（复用 `feishu patch`）与简历 PDF 渲染核对（复用 `rendering/`）。`candidate/` 等 Evidence 实现随概念废止一并删除。

每一步同时删除对应测试、更新能力目录，并跑完整门禁；每步一个提交，便于回退。

**验收：** 全仓 import / 引用扫描无残留；门禁通过；`README` 与宿主文档不再要求 SQLite、React 或 Console。

### P7 全局验收

用本人授权的一条合成岗位记录走完整链路：EM 填基本信息 → GM 写匹配与招呼语 → 本人修改并批准 → EM 读取批准并模拟执行（不真实发送）→ 结果回写与回读 → Signal 只记录本人操作 → Dream dry-run → Memory 发布回读 → 下一轮消费记录版本。另附门禁结果、依赖扫描、迁移对账与最终 ADR。

## 4. 本人裁定

| 编号 | 事项 | 影响阶段 | 状态 |
|---|---|---|---|
| D0 | 前置依赖：已安装并授权飞书或钉钉 CLI | P2 | 已定（钉钉未核验） |
| D1 | 只有本人能填 `已批准` / `已拒绝`，读取即视为批准，更新即 Signal；GM 评级后写 `待你批准` | P1 | 已定 |
| D2 | 材料表直接承接：一份简历 + 一份 Agent 组织的 md | P2 | 已定 |
| D3 | 代码只保留字段白名单与简历 PDF 渲染核对 | P6 | 已定 |
| D4 | 不启用高级权限，只做 GM / EM 隔离 | P2 | 已定 |
| D5 | `Muse处理` 由 GM 写、`GPT处理` 由 EM 写，下一轮非空即处理 | P1 | 已定 |
| D6 | EM 执行方式按平台选定；搜索间隔与各平台数量写入私有 `settings.json` | P2 | 已定 |
| D7 | 废止 Evidence 概念；材料与 Memory 由 GM 维护、不需本人审批，错误经 trace → Memory → 批准驳回闭环 | P1 | 已定 |

## 5. 分支与 PR 策略

- 本分支累积 P1–P7 的提交，不改动 PR #34、#35、#36 的远端分支。
- 完成后以一个面向 main 的新 PR 交付；PR #34–#36 是否关闭由本人决定。
- 未经本人要求不提交、不推送。

## 6. 可并行的工作

P1 内的 `AGENTS.md` 改写、角色 md、数据契约三份文档相互独立，可分开进行；P3 的 reference 精简与 P2 的 Setup reference 文件不重叠。P6 必须在 P3–P5 之后串行进行，且每步删除前重新核对消费者。

## 7. 进度记录（续做）

- **P3 文档门禁已收口。** 修正了失效的内部链接（lens-routing、resume-builder、oss-review、PRIVACY），`optimizer` 视角文档的 `EVID_*` 改称“材料事实”，两处 RUF001 全角标点以 `noqa` 标注；pytest、ruff、mypy 均绿。
- **已提交** `28a1b48`（P1–P3 检查点，含旧代码退役删除）。
- **`SKILL.md` 已改为角色路由入口：** 先读私有 `settings.json` 认角色，缺设置转 Initial Setup，再按 GM / EM 分表加载；EM 不加载写作与 Dream 技能。`lens-routing.md` 补上四个视角正文的链接，`agents/openai.yaml` 去掉“证据接地”旧说法。新增 3 个路由测试，门禁 91 passed。
- **未完成的 P3 项：** 能力目录未按新路径重写；`sources/*.yaml` 与 `references/oss/` 下的研究笔记未从入口链接，待能力目录重写时一并决定去留；greeting 与 `resume-builder.md` 中仍有 Evidence 术语（greeting 的 `evidence_collapse` 等标识符被测试锁定，改名需同步测试，暂未动）。
- **暂存区与测试数量需本人确认。** 工作区暂存了约 665 个删除（`src/jobagent` 303 个、`tests` 约 200 个、`frontend` 约 50 个），这些属于 P6 范围，但计划中 P6 尚未开始。当前 `pytest` 仅收集到 88 个测试，与上文 2154 的基线不再可比。
- **已恢复** `frontend/THIRD_PARTY_NOTICES.md` 的工作区文件并取消暂存：`docs/licensing.md` 与 `CONTRIBUTING.md` 要求第三方 notices 保留，删除它之前须先确认许可证义务已另有安排。
- 未提交、未推送。
