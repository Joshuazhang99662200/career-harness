# Initial Setup · 飞书 Base 最低 Schema（用户自行建立）

> 这是一份 **一个飞书 Base 内包含五张数据表** 的建表清单，不是要用户创建五个互不关联的 Base。第一次接入先建表，再运行 CareerHarness。已有符合条件的 Base 直接复用，不要求重新建立或迁移。
>
> 这是供新用户安装的通用字段契约；表名、ID、Base 链接、Bot 标识及用户材料均留在个人私有配置，不得写成仓库全局值。

## 使用者要做的事

1. 在飞书新建一个多维表格（Base），或打开自己已有的 Base。
2. 在同一个 Base 内按下列五个语义域创建工作表，**字段名称、字段类型和单选值保持一致**。文本首列可以兼作主字段。
3. 给运行 CareerHarness 的应用/Bot 授予必要的 Base 访问权限；本人保留实际审批权。所有 Agent 写操作应使用同一个 Bot 身份，避免人类 Trace 混入 Bot 操作。
4. 创建完成后，把 **Base 链接** 交给 Initial Setup Agent。不要在聊天里传 access token、appSecret、个人简历内容。
5. Agent 只读核对 schema 并展示差异；缺失/类型不对由本人修正。验收通过才初始化材料、配置 GM/EM、运行 Skill。

**零重复询问：** 已在私有配置里验证过同一 Base 的用户，不重复要求创建；仅检查本次 Skill 所需字段的变化。旧 Base 不因字段顺序不同而失败，类型与选项才是关键。不得默默创建第二套业务表。

## 五张表与字段定义

| 表 | 作用 | 首次运行最低要求 |
|---|---|---|
| 岗位 | 所有岗位、沟通、审批、终态与 GM↔EM 交接 | 必须 |
| 材料 | 个人简历 PDF、技能栈 MD、个人事实 MD | 必须 |
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
| `简历模板` | 附件（PDF） |
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

## 四个 Human Signals 自动化 Workflow

用户在五张表建好、Bot 身份已确认之后，按照 Base 官方自动化功能建立以下四条监听链：**岗位表指定字段发生变化 → Human Signals 追加记录**。每条至少写入 `source_table`、`source_record_id`、`job_title`、`field_name`、`field_id`、`signal_type`、`memory_domain`、`learning_status`。前后值、操作者身份与真实变更时点应由原生修改历史核实；Workflow 本身没有提供的不要猜测。

| 监听字段 | signal_type | memory_domain |
|---|---|---|
| `批准状态` | `approval_decision` | `approval` |
| `处理进度` | `workflow_outcome` | `workflow_context` |
| `招呼语` | `greeting_revision` | `greeting` |
| `匹配档位` | `matching_correction` | `search_match` |

上述四条必须逐条验收实际新增的 Signal。Dream 仅消费经过操作者历史核查的用户动作；Bot 动作、未知操作者不得直接形成个人偏好。Workflow 的创建或启用由本人完成或明确授权；Agent 不得越权创建或启用。

## 10 日谈与 48 小时运营不另起核心 Schema

- **常规交接：** GM / Analyst 写 `Muse处理`，Muse / EM 读取并写回 `GPT处理`；完整上下文留在对应岗位行的 `进展`，`待你处理（Memo）` 留给需要用户决策的事项。
- **48 小时自动收束：** 是否启用、起算点、时长及日历口径放私有 `settings.json`，不能写死给所有新用户。用户主动终止与 Bot 超时终止必须依真实修改历史区分；已明确的被动到期目标状态应采用本人的当前私有约定，不因模板擅改。
- **被动超时后的补查：** 读取岗位表已有事实，仅委托 Muse 查询缺少的 HR 最近活跃、真实已读/回信、岗位是否仍在招等；结果写 `GPT处理` 并在 `进展` 记录来源。空白回执不等于未读、未回复。
- **10 个工作日：** 是持续低转化异常的观察检查点，不是“每 10 天自动发报告”；证据不足时继续静默，不能把废弃岗位当已读不回样本。
- **可选扩展：** 未来如需跨岗位排队，可另外在同一 Base 增加「求职干预任务」表，但它不是首次使用的阻塞条件，不重新创建旧 Events 或 SQLite。
- **材料仓库：** `技能栈` 是独立文档，不是评分器或状态机；`事实整理` 是唯一事实资料入口之一，不由 EM 修改。

## 验收清单（Agent 执行，默认只读）

1. 能打开用户给的 Base，读取表名、字段名、真实类型、单选值，以及实际 Bot 身份。
2. 同一 Base 内可匹配五个语义域；同名不同类型、缺字段、缺选项要逐项报告；**不要伪称已经修复**。现有更多字段允许存在，不要求删表、重建或强制重命名。
3. 对 `岗位` 做一次分页只读和单条只读；对 `材料` 读取五个字段；对两份 Memory 表分别读取 Schema；不要读取大量无关个人资料来验结构。
4. 核查四条 Workflow 是否存在且有正确字段引用。若还没完成启用，必须明示“Dream 未就绪”，不能声称已自动学习。
5. 读取私有 `settings.json` 记录 Base/字段映射、Bot 身份及验证时间；**不要在公开仓库硬编码 ID、URL 或真实个人材料**。
6. 在用户批准的合成记录上做最小写入/回读验收，确保 GM 能写其允许字段、EM 能写其允许字段，任何 Agent 都不能写 `已批准`、`已拒绝`。没有授权时只读验收足够，但不能标记“写入已验证”。
7. 初始材料存在/已成功装载，角色和求职配置完整之后才允许进入业务 Skill：查岗、评级、写招呼、定向简历。Dream 和 10 日谈的调度/触发还需要各自独立验收，不能因为 Base 建好就声称已运行。

## 缺失时的对话指令

新用户没有 Base 时，只问一句：

> “请先在飞书建立一份 CareerHarness 多维表格，按建表清单配置五张工作表。建好后把 Base 链接发我，我来核验字段并继续初始化。”

用户已有 Base 时：

> “我会优先复用这份 Base，先核对现有字段。只列真正缺少或类型不符的地方，不要求你重建。”

不要每次 Skill 启动都重走 Setup，不要求用户手工审阅完整 Memory，不重复收集已在材料表里的个人信息。
