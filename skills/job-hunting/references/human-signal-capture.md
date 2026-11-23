# 仅本人修改触发 Human Signals

CareerHarness 以已登记的本人飞书身份为唯一 Trace 触发人。GM、EM、Bot、自动化、其他协作者和未知身份的变更均不写 Human Signals。Bot 写入的原值可作为之后本人编辑的对照值。

## 飞书入口与触发范围

- [飞书多维表格记录变更事件](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/drive-v1/event/list/bitable-record-changed)提供事件 ID、表版本、操作者 ID、记录与字段前后值和修改时间。以同一飞书应用下已核实的本人 `open_id` 或 `union_id` 做白名单。两个命名空间都已登记却发生冲突时不处理。通过订阅者列表或显示名无法确认本次操作者。
- 业务自动化和智能体写入使用各自可核实的非本人身份。此事件按提供的实际操作者 ID 归因。若某个写入器代表本人身份写字段，必须先隔离该写入方式，才能用这套链路验证本人手工修改。
- [订阅云文档事件](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/drive-v1/file/subscribe)是 Base 级订阅，参数没有按操作者筛选的能力。应用接收端才过滤实际写入人。需先配置并验证现有宿主的飞书事件接收能力，持授权以文档所有者或管理者身份订阅。核对本应用用户及应用身份所需 scope，优先使用适用的文档事件订阅和多维表格权限。
- [官方 Workflow Schema](https://github.com/larksuite/cli/blob/main/skills/lark-base/references/lark-base-workflow-schema.md)中的 `SetRecordTrigger.record_watch_info` 匹配修改前的记录状态，`recordModifiedUser` 是触发节点输出；两者均不能作为已经证实的本次改动操作者前置过滤。触发后加条件分支也不能作为节省[流程运行额度](https://www.feishu.cn/hc/zh-CN/articles/908751305974-%E5%A4%9A%E7%BB%B4%E8%A1%A8%E6%A0%BC%E5%B7%A5%E4%BD%9C%E6%B5%81%E4%BB%8B%E7%BB%8D)的依据。CareerHarness 不再默认创建或开启旧的全角色监听。

## 按操作者计划写入

1. 只从经飞书官方机制验签或认证的宿主接收器获取事件。订阅能力用该宿主实测验证。本机 `lark-cli` 1.0.91 的事件目录不识别 `drive.file.bitable_record_changed_v1`。可使用已配置的官方 SDK 接收入口；缺权限或入口时将 Trace 标为待接通。无需为岗位搜索、写作或本人批准重新启用旧 Workflow。
2. 单一接收宿主调用 `jobagent feishu human-trace-plan --contract <feishu-schema-bootstrap.md> --request <私有请求>`。请求包含业务 Base 的 `app_id`、`tenant_key`、`base_token`、`jobs_table_id`、真实 `fields={字段名:字段ID}`、登记身份 `operators` 和本次真实 `event`。身份目录中的 `human_open_ids` 与 `human_union_ids` 只能绑定同一个本人。Bot 可填 `bot_open_ids` 与 `bot_union_ids`。验签及原始事件数据留在受信任宿主，传入规划工具前移除不参与处理的敏感字段。只传当前事件和有必要的已验真 Bot 原始事件 `bot_events`。
3. 首次调用保留 `rows_complete=false`。只有本人真实修改已监听字段，且有完整、不同的前后值时才得到 `inspect_traces` 与确定的 `signal_ids`。Bot、协作者、未知身份和越界事件都不返回 Human Signals 查询或写入动作。
4. 在当前绑定的 Human Signals 表用 `signal_id` 精确查重，投影 `signal_id`、`event_id`、`source_record_id`、`field_id`、`before_value`、`after_value`、`source_context` 和反映真实记录的 `signal_record_id`。完成分页后把实际结果作为 `rows` 并置 `rows_complete=true`。结果不全时保持原状态。同一个 Base 的接收宿主串行完成查询、规划、写入和读回。发现重复记录、版本冲突或写入结果不明时先核实，禁止重复派发。
5. 只有 `write_traces` 可执行写入。使用注册 Bot 和同一个 Base 的 Human Signals 表。无 `signal_record_id` 时用 `base +record-batch-create` 按本次唯一 `signal_id` 创建；有真实记录 ID 时用 `base +record-batch-update` 更新原行。根据实时字段映射写入，`changed_at` 按已确认的 CLI 日期时间表示传入。检查写入业务结果和回读内容。该流程的写入目标限于 Human Signals。

## 同一岗位的前后值

稳定 `signal_id` 对应同一 Base、岗位记录与字段。不同岗位记录分别累积；同一个岗位字段只存原填值与本人最新采用值。只用同一应用、表和已确认 Bot 的真实、较早事件作为原填依据。后续本人编辑在原记录更新，重放和旧版本不再写入。Bot 新一轮写入发生时只有原填候选发生变化，等本人再次编辑才更新 Trace。

前后值按 JSON 序列化保存到文本列，保留显式空值、空字符串、数组和富文本。字段缺失时不从当前行补造。若当前本人真实修改有完整前后值，但缺少可核实的 Bot 原值，可记录已观察到的前后值并标为 `unknown`。原生 `event_id`、版本、时间和 Bot 来源信息保存在记录对应字段与 `source_context`。审批、流程进度和恢复 Bot 原值的编辑仅做 `context_only`。只有本人已核验且有 Bot 基线的匹配档位或招呼语修订，才置 `pending_dream`。Dream 按不同岗位 ID 的同类行为归纳。

## 切换和验收

先用 `base +workflow-list` 和 `+workflow-get` 核实旧流程。现有相关监听使用 [飞书配置流程](feishu-provisioning.md) 显示实际状态；仅在本人授权切换后，按核验的 ID 停用旧的 CareerHarness 全角色监听并读回状态。其他流程保留。新事件路径未接通时仍可正常工作，单独报告学习暂停。

使用授权的合成岗位，分别由本人、Bot、另一个协作者和不可识别的测试身份产生同类修改。核实只有本人的写入计划可到 Human Signals。重复派送同一事件，检查未创建第二条 Trace。同一岗位多次编辑检查最终值，换另一个岗位验证是独立记录。以当前飞书订阅及接收宿主的实际结果确认就绪。
