# 能力目录

仓库只保留两项代码能力：读写多维表格时的字段白名单，以及简历 PDF 的渲染与核对。其余工作由 GM、EM 按 Skill 完成，或由宿主自己的工具承担。状态只分 **已落地 / 仅契约 / 未开始 / 委托外部技能**。

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

## 按 Skill 完成的工作

| 能力 | 状态 | 说明 |
|---|---|---|
| Initial Setup | 已落地 | [first-use.md](first-use.md)，在对话里完成 |
| JD 评级 | 已落地 | GM 按 [GM.md](../roles/GM.md) 的档位口径完成 |
| 首条招呼 | 已落地 | [jd-greeting v1.2.0](../greeting/SKILL.md)：一条主线、逐条主张追溯、按作用域使用招呼语表达记忆；本人写作偏好只来自 Memory，不写进仓库 |
| 定向简历 | 已落地 | [简历优化](../optimizer/SKILL.md)：沿用私有设置里的母版与默认模式，不自动扩大可改范围；锁版 PDF 逐页比对与 `jobagent harness check-pdf` 分别报告 |
| EM 执行链路 | 已落地 | [em-execution.md](em-execution.md)：取数、去重入库、按 `批准状态` 执行、回执核对、超时收束、四行汇报 |
| BOSS / 猎聘 / 智联 / LinkedIn 取数与执行 | 委托外部技能 | EM 用本人选定的 Chrome 插件、云浏览器或 MCP 完成；各平台建设进度见 [em-execution.md](em-execution.md) 第 1 节，勾选不代表已完成实际操作验收 |
| 凌晨 Dream | 已落地 | GM 按 [memory-dream.md](memory-dream.md) 用 CLI 读写表格；调度由宿主承担 |
| 本人信号的 Workflow | 已落地 | 四条 Workflow 分别监听 `匹配档位`、`招呼语`、`处理进度`、`批准状态`，各向 Human Signals 追加一行；2026-11-21 经本人授权用 `lark-cli` 启用并读回 |
| 钉钉多维表格 | 未开始 | 钉钉 CLI 的表格读写尚未核验 |
