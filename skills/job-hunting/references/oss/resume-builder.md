# resume-builder 研究笔记

[StoneLL1/resume-builder](https://github.com/StoneLL1/resume-builder) · MIT · Agent Skill(SKILL.md + references/)· 可在 Claude Code / Codex / OpenClaw / Hermes 上运行。

本项目把它作为**可选渲染器与写作方法论来源**,不作为改写器。接入方式与职责切分见 [rendering-ats.md](../rendering-ats.md)。

## 它带来什么

- **XeLaTeX 单页编译**,成功判据明确(日志含 `Output written on resume.pdf (1 page)`)
- **中文模板选型**:6 套,源自 `dyweb/awesome-resume-for-chinese`,并给出 ATS 场景下优先单栏无表格无照片的建议
- **写作手艺**:量化公式、STAR / 场景化五步法、关键数据加粗、动词开头、每条 ≤ 2 行、经历排序优先级(实习 > 项目 = 科研 > 校园)、交付前检查清单
- **超页处理**:先收紧间距或砍经历,**不缩字号**——与本项目"超出必须先删减而不是缩字号"一致

## 与本项目口径不同的部分

它的 `claim-map` 记录"这条信息**有没有出处**、用户确认没有"(已确认 / 待确认 / 缺失阻塞 / 已省略)。本项目的事实来源只有材料表里的那份 md 与原始简历,写出的每句话是否有依据由 GM 按 [质量门禁](../optimizer/quality-gates.md) 自查,错误经本人驳回或修改进入 Dream。`claim-map` 不代替这一步。

## 采信边界

- 它的 `SKILL.md` 与 `references/` 是**参考资料**,不内联进本项目的运行时指令;运行时指令仍由本项目 optimizer 策略文档组装
- 交给它渲染的必须是 GM 已自查过的最终正文
- 它的「重包装」口径略松、「引导给数字」会制造出数字压力;冲突时一律以 [事实边界](../../optimizer/SKILL.md#事实边界) 与 [quality-gates.md](../optimizer/quality-gates.md) 为准,**没有数字就留白**
- 它自带的 PDF 解析与信息收集流程不使用,个人资料只来自材料表
- 输出 PDF 仍须通过 `jobagent harness check-pdf`
