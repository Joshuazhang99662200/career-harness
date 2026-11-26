# 补证：只让 EM 去看表里证明不了的东西

GM 在 `Muse处理` 写委托，EM 在 `GPT处理` 写回执，格式与去重规则见 [多维表格契约](../../references/bitable-contract.md) 的交接留言一节；超时后的自动补证见 [EM 执行链路](../../references/em-execution.md) 第 6A 节。

## 写委托之前

1. 先看这一行的 `Muse处理` 与 `GPT处理` 里有没有同一个 `request_id`，或早先写下的 `CH10D-` 委托与回执。已有结果就直接用；委托尚未接单就等待 EM 的回执，不再写一份。接单回执只证明 EM 的所选宿主读到了委托，不证明已取得平台结果。
2. 只问表里没有的：真实的发送 / 已读 / 回复 / 索取简历 / 约面，招聘方最近活跃的原始标签，岗位是否还在招，最近一次完整巡检的时间，在线简历被看到时的版本。
3. 不要求 EM 重抓 JD、薪资、档位或招呼语。

## 委托格式

```text
CH10D-<岗位ID>-<probe类型>-<日期> | origin=<system_timeout|early_probe|ten_workday_decline|unknown> | request_id=<同一任务键>
need=<hr_activity, read_receipt, substantive_reply, listing_status, last_full_patrol, exposure_version 中需要的几项>
known=<表里已经有、无需再查的项>
```

EM 在安装时选定的宿主每轮先扫 `Muse处理`，对新任务先在 `GPT处理` 追加 `request_id=<同一任务键> | status=accepted | observed_at=<实际读到时间> | host=<当前宿主>` 并读回；无可用平台入口就写 `status=blocked` 和具体原因。平台核查结束后追加同键的 `status=completed|partial|blocked`、逐项原始结果、来源、观察时间和未查到的原因，再读回。相同键只接单一次；结果不明先查已有回执，不重复平台操作。

## 读回执

- `status=blocked` 或 `unknown` 的项照原样计入 `unknown`，不推断；`unobservable` 计入 `unobservable`。
- 招聘方“近期活跃”只是辅助观察，不能推出“对方在线却故意不回”。
- 回执说明对方其实已回复、表里进度却没跟上的，先让 EM 对账，再重算指标。
- 任务写下了不等于已执行；没有回执就按 `unknown` 处理。
- GM 读回 `GPT处理` 中相同 `request_id` 的接单与结果，核对 `need` 的每一项；仅 `accepted` 不算完成。`blocked`、`partial` 或缺项继续保持未知，不能为了按时提醒而补造归因。
