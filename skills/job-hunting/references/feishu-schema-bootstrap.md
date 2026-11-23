# Initial Setup · 飞书 Base Schema

本清单是 [Initial Setup](first-use.md) 的 Schema 来源。首次接入在同一份飞书 Base 内自动补齐五张数据表，已有符合条件的资源直接复用。Human Signals 通过 [飞书原生事件与本人过滤](human-signal-capture.md) 单独接入。
真实资源 ID、Base 链接、Bot 标识及用户材料存入个人私有配置。每表第一列是文本主字段。表中字段行由 `jobagent setup feishu-plan` 读取，变更类型、枚举或表结构时直接更新本表并运行契约测试。

## 五张表与字段定义

| 表 | 作用 | 首次运行最低要求 |
|---|---|---|
| 岗位 | 所有岗位、沟通、审批、终态与 GM↔EM 交接 | 必须 |
| 材料 | 简历模板及 GM 维护的技能栈与个人事实 Markdown。表结构必备，附件按需补齐 | 必须 |
| Human Signals | 用户编辑轨迹，供 Dream 分析 | 完整版必须 |
| 搜索与匹配记忆 | Dream 发布的 Search Memory；PA/EM 消费 | 完整版必须 |
| 招呼语表达记忆 | Dream 发布的 Greeting Memory；GM 消费 | 完整版必须 |

### 岗位（20 列）

| 字段 | 飞书字段类型 / 选项 |
|---|---|
| `岗位ID` | 文本（首列） |
| `岗位名` | 文本 |
| `公司` | 文本 |
| `招聘平台` | 单选：BOSS/智联/猎聘/ATS/小红书/LinkedIn |
| `原岗位链接` | 网址或文本 |
| `薪资原文` | 文本 |
| `JD摘要` | 文本 |
| `JD全文` | 附件 |
| `匹配档位` | 单选：A/B/C/D |
| `匹配理由` | 文本 |
| `招呼语` | 文本 |
| `邮件正文` | 文本 |
| `简历cv（PDF）` | 附件 |
| `批准状态` | 单选：待你批准/已批准/已拒绝/已终止 |
| `处理进度` | 单选：初次入库/招呼语（初稿）/首次沟通/对方已读/对方交互中/对方要简历/简历已投/面试已约/已终止/已废弃 |
| `更新时间` | 日期时间 |
| `进展` | 文本 |
| `待你处理（Memo）` | 文本 |
| `Muse处理` | 文本 |
| `GPT处理` | 文本 |

### 材料（5 列）

| 字段 | 飞书字段类型 / 选项 |
|---|---|
| `材料ID` | 文本（首列） |
| `岗位类型` | 文本 |
| `简历模板` | 附件（PDF 或 Word 简历） |
| `技能栈` | 附件（Markdown） |
| `事实整理` | 附件（Markdown） |

### Human Signals（19 列）

| 字段 | 飞书字段类型 / 选项 |
|---|---|
| `signal_id` | 文本（首列） |
| `event_id` | 文本 |
| `source_table` | 文本 |
| `source_record_id` | 文本 |
| `job_title` | 文本 |
| `field_name` | 文本 |
| `field_id` | 文本 |
| `signal_type` | 文本 |
| `memory_domain` | 文本 |
| `learning_status` | 文本 |
| `operator_id` | 文本 |
| `operator_name` | 文本 |
| `before_value` | 文本 |
| `after_value` | 文本 |
| `source_context` | 文本 |
| `changed_at` | 日期时间 |
| `captured_at` | 日期时间 |
| `dream_run_id` | 文本 |
| `memory_version` | 文本 |

### 搜索与匹配记忆（19 列）

| 字段 | 飞书字段类型 / 选项 |
|---|---|
| `memory_id` | 文本（首列） |
| `summary` | 文本 |
| `role_directions` | 文本 |
| `keywords` | 文本 |
| `exclusions` | 文本 |
| `positive_patterns` | 文本 |
| `negative_patterns` | 文本 |
| `negative_signals` | 文本 |
| `priority_factors` | 文本 |
| `calibration_rules` | 文本 |
| `source_signal_ids` | 文本 |
| `dream_run_id` | 文本 |
| `content_hash` | 文本 |
| `status` | 文本 |
| `version` | 数字 |
| `confidence` | 数字 |
| `created_at` | 日期时间 |
| `published_at` | 日期时间 |
| `memory_md` | 附件 |

### 招呼语表达记忆（17 列）

| 字段 | 飞书字段类型 / 选项 |
|---|---|
| `memory_id` | 文本（首列） |
| `summary` | 文本 |
| `preferred_tone` | 文本 |
| `preferred_openings` | 文本 |
| `avoid_phrases` | 文本 |
| `emphasis` | 文本 |
| `role_specific_patterns` | 文本 |
| `good_examples` | 文本 |
| `bad_examples` | 文本 |
| `source_signal_ids` | 文本 |
| `dream_run_id` | 文本 |
| `content_hash` | 文本 |
| `status` | 文本 |
| `version` | 数字 |
| `confidence` | 数字 |
| `created_at` | 日期时间 |
| `published_at` | 日期时间 |

## 四种 Human Signals 字段映射

飞书事件确认是本人修改岗位表中的以下字段时，才写入同一 Base 的 Human Signals。前后值保留 JSON 语义，操作者、原生事件 ID 与编辑时间取自可信的原生事件。岗位和字段相同的后续修改更新现有 Trace。

| 监听字段 | signal_type | memory_domain |
|---|---|---|
| `批准状态` | `approval_decision` | `approval` |
| `处理进度` | `workflow_outcome` | `workflow_context` |
| `招呼语` | `greeting_revision` | `greeting` |
| `匹配档位` | `matching_correction` | `search_match` |

审批与流程结果只保留上下文。匹配和招呼语只有本人修改和 Bot 原值均已核实时，才可进入 Dream。

## 10 日谈与 48 小时运营不另起核心 Schema

- **常规交接：** GM / Analyst 写 `Muse处理`，Muse / EM 读取并写回 `GPT处理`；完整上下文留在对应岗位行的 `进展`，`待你处理（Memo）` 留给需要用户决策的事项。
- **48 小时自动收束：** 是否启用、起算点、时长及日历口径放私有 `settings.json`，不能写死给所有新用户。用户主动终止与 Bot 超时终止必须依真实修改历史区分；已明确的被动到期目标状态应采用本人的当前私有约定，不因模板擅改。
- **被动超时后的补查：** 读取岗位表已有事实，仅委托 Muse 查询缺少的 HR 最近活跃、真实已读/回信、岗位是否仍在招等；结果写 `GPT处理` 并在 `进展` 记录来源。空白回执不等于未读、未回复。
- **10 个工作日：** 是持续低转化异常的观察检查点，不是“每 10 天自动发报告”；来源依据不足时继续静默，不能把废弃岗位当已读不回样本。
- **可选扩展：** 未来如需跨岗位排队，可另外在同一 Base 增加「求职干预任务」表，但它不是首次使用的阻塞条件，不重新创建旧 Events 或 SQLite。
- **材料仓库：** `技能栈` 是独立文档，不是评分器或状态机；`事实整理` 是唯一事实资料入口之一，不由 EM 修改。

## 验收清单（Agent 执行，默认只读）

1. 能打开用户给的 Base，读取表名、字段名、真实类型、单选值，以及实际 Bot 身份。
2. 同一 Base 内可匹配五个语义域；同名不同类型、缺字段、缺选项要逐项报告；**不要伪称已经修复**。现有更多字段允许存在，不要求删表、重建或强制重命名。
3. 对 `岗位` 做一次分页只读和单条只读；对 `材料` 读取五个字段；对两份 Memory 表分别读取 Schema；不要读取大量无关个人资料来验结构。
4. 独立核查原生事件入口、本人修改验收和旧 Workflow 状态。未切换或未验收时如实显示 Trace 与 Dream 待就绪。
5. 读取私有 `settings.json` 记录 Base/字段映射、Bot 身份及验证时间；**不要在公开仓库硬编码 ID、URL 或真实个人材料**。
6. 在用户批准的合成记录上做最小写入/回读验收，确保 GM 能写其允许字段、EM 能写其允许字段，任何 Agent 都不能写 `已批准`、`已拒绝`。没有授权时只读验收足够，但不能标记“写入已验证”。
7. 初始材料存在/已成功装载，角色和求职配置完整之后才允许进入业务 Skill：查岗、评级、写招呼、定向简历。Dream 和 10 日谈的调度/触发还需要各自独立验收，不能因为 Base 建好就声称已运行。

## 缺失时的对话指令

新用户没有 Base 时，只问一句：

> “请先在飞书建立一份 CareerHarness 多维表格，按建表清单配置五张工作表。建好后把 Base 链接发我，我来核验字段并继续初始化。”

用户已有 Base 时：

> “我会优先复用这份 Base，先核对现有字段。只列真正缺少或类型不符的地方，不要求你重建。”

不要每次 Skill 启动都重走 Setup，不要求用户手工审阅完整 Memory，不重复收集已在材料表里的个人信息。
