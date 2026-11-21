# 补证：只让 EM 去看表里证明不了的东西

GM 在 `Muse处理` 写委托，EM 在 `GPT处理` 写回执，格式与去重规则见 [多维表格契约](../../references/bitable-contract.md) 的交接留言一节；超时后的自动补证见 [EM 执行链路](../../references/em-execution.md) 第 6A 节。

## 写委托之前

1. 先看这一行的 `Muse处理` 与 `GPT处理` 里有没有同一个任务键，或早先写下的 `CH10D-` 委托与回执。已有回执就直接用；委托还没回执就等它，不再写一份。
2. 只问表里没有的：真实的发送 / 已读 / 回复 / 索取简历 / 约面，招聘方最近活跃的原始标签，岗位是否还在招，最近一次完整巡检的时间，在线简历被看到时的版本。
3. 不要求 EM 重抓 JD、薪资、档位或招呼语。

## 委托格式

```text
CH10D-<岗位ID>-<probe类型>-<日期> | origin=<system_timeout|ten_workday_decline|unknown>
need=<hr_activity, read_receipt, substantive_reply, listing_status, last_full_patrol, exposure_version 中需要的几项>
known=<表里已经有、无需再查的项>
```

## 读回执

- `status=blocked` 或 `unknown` 的项照原样计入 `unknown`，不推断；`unobservable` 计入 `unobservable`。
- 招聘方“近期活跃”只是辅助观察，不能推出“对方在线却故意不回”。
- 回执说明对方其实已回复、表里进度却没跟上的，先让 EM 对账，再重算指标。
- 任务写下了不等于已执行；没有回执就按 `unknown` 处理。
