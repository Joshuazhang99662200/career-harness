---
name: performance-intervention
description: CareerHarness 的 10 日谈：GM 每轮发现窗口前的补证需要，满 10 工作日闭合窗口再正式检查；平时静默，只有两个不重叠窗口都持续偏低、EM 补证和混杂因素排查充分时，才向本人提出可批准方案。Ten-workday funnel check with early GM-to-EM fact gathering; silent until sustained, attributed decline. 不改文案、不向招聘方发消息、不写 Memory。
---

# 10 日谈：持续异常才说话

只有 GM 加载本技能。业务事实只来自岗位表、`Human Signals` 与原生修改历史（`jobagent feishu record-history`）；EM 的补证回执在 `GPT处理`。本技能不建表、不存状态、不写 Memory：Memory 只由 Dream 发布，EM 与 PA 只读。

## 什么时候运行

GM 每轮先做轻量发现，消费已有补证回执并按 [指标](references/metrics.md) 检查窗口闭合前的提前补证条件；需要平台事实时加载 [补证](references/em-probe.md) 委托 EM。每满一个 10 工作日的闭合窗口，再做正式漏斗检查。没到窗口末尾、或窗口还没闭合，就不能判定持续下降或向本人提案。

## 默认静默

下面任一情况都只记一行观察，不打扰本人、不生成提案：

- 指标正常；
- 只有一个窗口偏低（记为 `watching`）；
- 样本没成熟、样本太少、没有可比的历史基准；
- `unknown` 或 `unobservable` 占比过高，测量本身不可信。
- 窗口闭合前的风险信号只用来提前补证，不向本人报告下降结论。

## 什么时候说话

两个**不重叠**的相邻闭合窗口里，同一可比切片的成熟指标都低于基准的 0.8 倍（候选阈值，本人可在私有设置里改），并且按 [归因](references/attribution.md) 排查过混杂因素，依据仍指向同一个可改的对象，才向本人提出方案。依据不够时，先按 [补证](references/em-probe.md) 让 EM 补，不向本人下结论。

## 按需加载

| 步骤 | 加载 |
|---|---|
| 算指标、判成熟、判持续 | [references/metrics.md](references/metrics.md) |
| 排查混杂因素、决定改什么 | [references/attribution.md](references/attribution.md) |
| 表里证明不了、需要 EM 去平台看 | [references/em-probe.md](references/em-probe.md) |
| 写提案、等批准、执行后复核 | [references/intervention-approval.md](references/intervention-approval.md) |

## 硬性边界

- 不写 Memory，不替 Dream 归纳本人偏好。
- 不改招呼语、简历、档位或筛选条件，除非本人批准了具体方案；批准方案也不等于批准发送。
- 不把低回复率直接归因于文案；不把超时、招聘方拒绝或岗位下线当作本人偏好。
- 不向招聘方发消息、不投递、不自动回滚；向本人提出已归因的方案按本技能的提醒门槛执行。
