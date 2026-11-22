# 能力目录

仓库代码提供 Initial Setup 的对账与路由、表格字段白名单，以及简历 PDF 的渲染与核对。发现与执行由 Skill 调用官方 CLI 或宿主的已授权入口。状态只分 **已落地 / 仅契约 / 未开始 / 委托外部技能**。

`tests/test_capability_status.py` 会双向核对本表列出的命令与实际安装的命令；新增或删除命令时同步更新本表。

## 命令

| 能力 | 状态 | 入口 |
|---|---|---|
| 读取实时字段结构 | 已落地 | `jobagent feishu schema`：按私有配置读取一张表的实时字段；不修改表结构 |
| 按条件读取记录 | 已落地 | `jobagent feishu query`：GM、EM 共用字段映射与 AND 条件；显式取数上限与 offset，`has_more` 不等于读完 |
| 读取单条记录 | 已落地 | `jobagent feishu get`：返回映射字段与内容摘要 |
| 读取单条记录历史 | 已落地 | `jobagent feishu record-history`：调用官方记录历史；历史没读完就失败 |
| 字段回写（字段白名单） | 已落地 | `jobagent feishu patch`：按角色白名单只写归属字段；GM 对批准字段只能写“待你批准”；写后读回 |
| 简历 PDF 渲染 | 已落地 | `jobagent harness render`：把已定稿的简历渲染为 PDF / Word，并对 PDF 运行文字核对 |
| 简历 PDF 核对 | 已落地 | `jobagent harness check-pdf`：核对 PDF 文字、页数与内部批注 |
| 飞书配置对账 | 已落地 | `jobagent setup feishu-plan`：根据实测快照与唯一 Schema 生成下一阶段动作及绑定 |
| 招聘平台能力路由 | 已落地 | `jobagent setup platform-routes`：选择当前宿主及运行模式下已验收的入口 |

## 按 Skill 完成的工作

| 能力 | 状态 | 说明 |
|---|---|---|
| Initial Setup | 已落地 | [first-use.md](first-use.md)，按官方 CLI 完成飞书配置、验收与平台选择。宿主和平台实测结果分别记录 |
| JD 评级 | 已落地 | GM 按 [GM.md](../roles/GM.md) 的档位口径完成 |
| 首条招呼 | 已落地 | [jd-greeting v1.2.0](../greeting/SKILL.md)：一条主线、逐条主张追溯、按作用域使用招呼语表达记忆；本人写作偏好只来自 Memory，不写进仓库 |
| 定向简历 | 已落地 | [简历优化](../optimizer/SKILL.md)：沿用私有设置里的母版与默认模式，不自动扩大可改范围；锁版 PDF 逐页比对与 `jobagent harness check-pdf` 分别报告 |
| EM 执行链路 | 已落地 | [em-execution.md](em-execution.md)：取数、去重入库、按 `批准状态` 执行、回执核对、超时收束、四行汇报 |
| 各招聘平台取数与执行 | 委托外部技能 | [平台能力路由](platform-capability-routing.md) 按每个宿主的实测记录选择入口 |
| 凌晨 Dream | 已落地 | GM 按 [memory-dream.md](memory-dream.md) 用 CLI 读写表格；调度由宿主承担 |
| 超时收束与超时后补证 | 已落地 | [em-execution.md](em-execution.md) 第 6、6A 节：时钟取原生历史里最近一次 `处理进度` 变化或入库时间，交接字段写入不重置；每次超时派生一次 CH10D 补证，回执写 `GPT处理`；宿主实际运行未验收 |
| 10 日谈 | 仅契约 | [performance-intervention](../performance-intervention/SKILL.md)：10 工作日闭合窗口、两窗持续偏低才提案、本人批准后执行与复核；GM 宿主的定时触发尚未配置与验收 |
| 本人信号的 Workflow | 已落地 | [飞书配置流程](feishu-provisioning.md) 按实时引用复用或创建并启用四条监听。既有 Base 曾启用并读回四条。新工作区仍逐条验收触发结果 |
| 钉钉多维表格 | 未开始 | 钉钉 CLI 的表格读写尚未核验 |
