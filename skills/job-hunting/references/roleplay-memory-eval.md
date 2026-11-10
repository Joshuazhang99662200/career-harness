# 记忆系统长程角色扮演验证

本页只在本人要求用角色扮演验证记忆系统时加载。全程使用合成人设、合成证据和合成岗位，工作区独立，**不发送任何消息，结果不能用于真实投递**。

## 与上一版（`f704173`）相比的变化

重跑前先知道这些，避免把行为变化误判为故障：

- 记忆更新改为增量：总结一步只输出新增、修订、合并、作废，没有变化的规则由程序原样保留。合并必须保留被合并规则的全部来源；作废必须引用推翻它的新反馈。
- 先泛化：同一偏好在两个以上不同岗位的反馈里出现就合并成通用规则；`role` 规则的条件不能写岗位标题或公司名，否则这一步失败。通用规则每轮直接生效，模型只在范围规则里挑选。
- 复核要逐条判定已选规则（遵守、违反、不适用）；任何一条违反都会退回重写一次。
- 允许在不改事实的前提下改写证据措辞；`greeting-ai.md` 去掉了维护者个人的禁用词和数字写法，上一轮“不客套”的部分效果来自这份策略文档，本轮不再有。
- 起草前有方向判断：学到的岗位规则覆盖当前 JD 时，本轮不起草，状态为 `skip_proposed`。
- 每次模型调用写入 `.jobagent/roleplay/calls.jsonl`，不再需要外部透传包装。
- 记忆历史备份改名为 `history/<版本>.md`，路径更短。
- 跳过答复（`confirm_skip`、`override_skip`）会学进 memory，修正方向判断同一类岗位时准时不准。
- 规则可以带 `forbidden_phrases`：本人改写时删掉的原文片段（例如自报姓名、结尾客套）。稿子里再出现就由程序直接退回重写，不经复核模型判断。
- 去掉了 `json_schema_flag`：agy 的 `--json-schema` 会多跑一个 `finish` 工具步骤，在纯文本边界下每次都失败关闭。

## 分工

| 角色 | 谁 | 能看到什么 |
|---|---|---|
| 求职者本人 | 本机 Claude Code 会话（扮演合成人设） | `roleplay persona` 的人设与隐藏偏好；每轮的 JD 与招呼 |
| 起草、独立复核、记忆总结与选择 | 本机 Gemini CLI | 只有程序打包的 JD、已确认证据、记忆规则与本人反馈原话；**不含人设和隐藏偏好** |
| 裁判 | `roleplay report` | 六项不变式、隐藏偏好是否被记忆学到、前后半程通过率 |

Gemini 能学到偏好的唯一途径，就是本人每轮留下的决定、改写原文和理由。报告里某条隐藏偏好显示已捕获，说明这条链路是通的。

## 准备（只做一次）

1. 在本机克隆仓库、切到包含本功能的分支，`python -m pip install -e .`。
2. 确认本机装的是哪种 CLI，并已登录。两种都支持，由配置里的 `protocol` 区分：
   - **Gemini CLI（`gemini`）**：`echo "只回复 {\"ok\": true}" | gemini --output-format json`，输出里应有 `response` 和 `stats.tools.totalCalls`。
   - **Antigravity CLI（`agy`）**：`agy models` 应列出要用的模型。agy 的最终结果不报告工具调用次数，而且无人值守时读文件不经授权，所以必须用 stream-json，从过程事件里数工具调用。

   输出证明不了"没用工具"时，`roleplay round` 会失败关闭，不会重试。
3. 新建一个**空目录**作为工作区并进入，后续命令都在这里运行。写私有配置 `.jobagent/gemini.json`，二选一：

```json
{"argv": ["gemini", "--output-format", "json"], "timeout_seconds": 180}
```

```json
{
  "protocol": "agy_stream_json",
  "argv": ["<agy 可执行文件完整路径>", "-p=", "--input-format", "stream-json",
           "--output-format", "stream-json", "--model", "gemini-3.8-flash-high"],
  "timeout_seconds": 600
}
```

agy 每次调用实测要 1 到 3 分钟，一轮要调用多次；超时设到 300 秒时曾有一次调用超时，所以示例用上限 600 秒。超时也按失败处理，不重试。

可选配置（不写即关闭）：

| 键 | 作用 |
|---|---|
| `repair_retries` | 设为 `1` 时，只对三类机械失败各重试一次：JSON 语法错误、超出输出 token 上限、流中断；重试提示要求输出更短。契约不符和工具活动仍直接失败，不重试 |
| `steps` | 按输出契约名覆盖 argv 或超时，例如 `{"PreferenceEditSet": {"argv": [...低档模型...], "timeout_seconds": 300}, "PreferenceApplication": {"timeout_seconds": 120}}`；契约名还有 `DirectionCheck`、`GreetingDraft`、`GreetingReview` |

每次调用都追加一行到 `.jobagent/roleplay/calls.jsonl`：步骤、第几次尝试、状态或失败类别、耗时、模型耗时、token 用量与回复长度，不记录提示词和回复原文。

Gemini CLI 指定模型时在 argv 里加 `"-m", "<模型名>"`；agy 用 `agy models` 里的模型编号。不要在配置里放密钥，也不要加 `--dangerously-skip-permissions`、`--yolo` 这类自动批准工具的参数，配置会直接拒绝。

两种 CLI 都可能读取用户级的全局上下文（如 `~/.gemini/GEMINI.md`）。里面若有写作或求职偏好，会和记忆规则一起影响 Gemini，测出来的就不只是记忆链路；运行前先确认，必要时在报告里注明。

4. `jobagent roleplay init --scenario evaluation_first_v1`，再 `jobagent roleplay persona` 读一遍人设。可选参数：
   - `--memory-mode full|notes_only|off`：`full` 使用偏好记忆加最近反馈原话；`notes_only` 只给生成方最近反馈原话、不用记忆规则；`off` 两者都不给。三个臂各用一个独立空目录跑同样轮数，才能把批准率的提升归因到记忆。
   - `--strict-owner`：扮演方的原话和理由里出现“所有、不管、每封、任何岗位、无论、一律”等全称词时，`decide` 直接拒绝。用来检验真实用户不说这类话时，记忆能否自己归纳。

## 每一轮

1. `jobagent roleplay round --gemini-config .jobagent/gemini.json`。输出含 JD、`greeting`、本轮所选规则 `selected_rule_texts`。`generation_status` 为 `rejected` 时说明 Gemini 的稿子没过独立复核，记下原因，直接进入下一轮。
2. 以人设身份判断，按隐藏偏好和常识只选一个动作：
   - `approve`：完全满足偏好；
   - `revise`：岗位可以但文字不行，`revised_text` 写本人改好的全文；
   - `decline`：岗位方向不要，`reason_category` 选 `direction`。
   - 如果 `generation_status` 是 `skip_proposed`：说明已学到的岗位规则建议跳过这个岗位，没有起草。看 `direction_rule_ids` 和 `direction_reason`，按人设决定 `confirm_skip`（确认跳过）或 `override_skip`（仍要联系，下一轮会对同一岗位不经方向判断直接起草）。这两种答复都会登记为对所引岗位规则的反馈，下一轮刷新 memory 时学进去：确认说明规则覆盖得对（条件可以放宽到这类岗位），推翻说明规则管得太宽。`note` 照样要写一句理由，严格本人模式同样检查全称词。
3. 写决定文件 `.jobagent/roleplay/decisions/R<轮次>.json`（目录不存在时先创建），再执行 `jobagent roleplay decide <轮次> <文件>`：

```json
{
  "action": "revise",
  "words": "改一下：先讲评测，别说很感兴趣。",
  "reason_category": "copy",
  "note": "开头先讲搭评测体系的经历，删掉客套话",
  "revised_text": "您好，我在知识库问答产品里搭过评测集……",
  "triggered_preferences": ["P_EVAL_FIRST", "P_NO_PLEASANTRIES"]
}
```

扮演规则：

- **`note` 每次都要写一句本人理由。** 没有理由的单次决定，程序不允许被总结成通用偏好，这是设计如此，不是故障。
- `triggered_preferences` 只填这次决定实际依据的隐藏偏好编号，供裁判核对，不会传给 Gemini。
- `words`、`note` 和改写文字里**不要照抄隐藏偏好原文**，要像真人一样用自己的话反馈。否则测出来的是抄写，不是学习。
- 不要编造人设证据之外的经历；改写只能使用已确认的合成证据。
- 不直接改数据库或记忆文件，所有动作只通过上述命令完成。

4. 每 5 轮运行一次 `jobagent roleplay report`。

## 长程运行

在本机 Claude Code 里可以用 `/loop` 让会话自己控制节奏，例如把下面整段作为循环提示：

```text
在当前目录继续 CareerHarness 记忆角色扮演验证，按 skills/job-hunting/references/roleplay-memory-eval.md 执行。
你扮演 `jobagent roleplay persona` 里的合成人设。每次唤醒完成一轮：round → 按人设判断 → 写决定文件 → decide。
每 5 轮跑一次 report，把不变式失败、新捕获的偏好和通过率变化追加到 .jobagent/roleplay/journal.md。
任一不变式失败、Gemini 连续 3 轮失败或生成被拒，或已完成 40 轮时，停止循环并汇报。
```

14 个合成岗位会循环出现，第二遍遇到同一 JD 时可以直接对比前后稿件。

## 怎么读报告

- `memory_mode`：本臂的记忆设置；`off` 和 `notes_only` 下，记忆相关的检查标为不适用。
- `preferences[].rounds_selected_after_trigger` 与 `approved_when_selected`：偏好第一次触发之后，对应规则真的被选用（招呼类）或被方向判断引用（岗位类）的轮数，以及其中被批准（或确认跳过）的轮数。这比“记忆里出现关键词”更能说明规则在起作用。
- `actions.skip_proposed`、`confirm_skip`、`override_skip`：方向判断提出跳过的次数和扮演方的答复。

- `checks` 中任何一项为 false 都是记忆系统缺陷，优先排查，不要继续刷轮次。
- `preferences[].captured`：在对应类别的记忆规则里出现了关键词即判为捕获。关键词判定只是粗筛，最终以 `matching_rules` 原文是否真表达了该偏好为准。
- 触发过却始终未捕获的偏好，说明反馈没有被总结成规则，或总结得太保守，属于需要改进的地方。
- `first_half_acceptance` → `second_half_acceptance` 上升，说明记忆在起作用。样本小时只看方向，不作统计结论；要看统计意义，用 `memory simulate` 估计需要的轮数。
- `P_NO_SALES` 属于 jobs 类偏好，只影响后续找岗，不影响招呼。它被捕获，只说明回绝理由进入了记忆。
