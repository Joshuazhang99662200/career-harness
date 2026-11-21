---
name: performance-intervention
description: CareerHarness 的 10 日谈：每满一个 10 工作日的闭合窗口，GM 用岗位表与原生修改历史做一次低成本漏斗检查；平时静默，只有两个不重叠窗口都持续偏低、混杂因素排查过且依据充分时，才向本人提出具体可批准的优化方案，批准后才执行并复核效果。Ten-workday funnel check for CareerHarness; silent by default, proposes only on sustained, well-supported decline. 不改文案、不发消息、不写 Memory。
---

# 10 日谈：持续异常才说话

只有 GM 加载本技能。业务事实只来自岗位表、`Human Signals` 与原生修改历史（`jobagent feishu record-history`）；EM 的补证回执在 `GPT处理`。本技能不建表、不存状态、不写 Memory：Memory 只由 Dream 发布，EM 与 PA 只读。

## 什么时候运行

每满一个 10 工作日的闭合窗口，在 GM 的既有例行轮里做一次检查。没到窗口末尾、或窗口还没闭合，就不算。

## 默认静默

下面任一情况都只记一行观察，不打扰本人、不生成提案：

- 指标正常；
- 只有一个窗口偏低（记为 `watching`）；
- 样本没成熟、样本太少、没有可比的历史基准；
- `unknown` 或 `unobservable` 占比过高，测量本身不可信。

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
- 不发消息、不投递、不自动回滚。
