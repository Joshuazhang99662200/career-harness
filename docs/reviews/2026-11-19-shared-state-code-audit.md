# 共享业务状态机：代码层级专项审查

日期：2026-11-19。本地 HEAD：`57ba6ba0cd3dd736a7cf02e919db74045e72dd06`，加本轮开始前已有工作树改动。本人在对话中明确：共享多维表格为 GPT/Muse/人类共同操作的业务环境与唯一业务状态源，阶段动作由 `处理进度 × 批准状态` 联合定义；漏写与结果交代应在 Agent 规范和实际定时任务正文约定。

本轮检查代码、契约和测试，修订规范与实施任务；没有更换存储实现、删除审批校验、修改真实 Base 或部署宿主任务。真实宿主运行代码与定时任务正文未取得，不能从本地接线缺口推断 Muse 当前全部动作的实际情况。

## 检查范围

| 层级 | 检查对象 | 当前结论 |
|---|---|---|
| 类型契约 | `schemas/pipeline.py`、`outreach.py`、`worker.py`、`host_checks.py` | 现有本地契约不含共享 Base 的联合状态来源绑定 |
| 决定与领取 | `bridge/panel_decisions.py`、`bridge/worker.py`、`outreach/service.py` | 消费本地 ask/batch/approval，未直接消费表内联合状态 |
| 业务状态与证明 | `storage/pipeline_repository.py`、`storage/pipeline_proofs.py` | 读本地 pipeline 与本地获批发送证明 |
| 动作与结果 | `bridge/worker.py`、`schemas/worker.py` | 有本地事务、幂等、准确回读与未知结果保护，无共享环境回写验证 |
| 轮次报告 | `storage/host_reports.py`、`schemas/host_checks.py` | 核验本地搜索证据，保存 unfinished；不验证共享表逐项闭环 |
| 宿主约定 | `AGENTS.md`、`hosts/personal-ai/{README,memory,tasks}.md` | 原约定有本地权威和重复批准倾向，已在本轮修订为共享模式要求 |

对 `src/`、`tests/`、`scripts/`、`hosts/` 检索飞书字段名及 feishu/bitable 等标识，当前本地未发现对应适配器；再由上表的调用链确认本地路径。搜索无命中本身不证明远端宿主、连接器插件或真实账号没有相应实现。

## C1：共享批准尚无消费路径，本地记录形成额外依赖（高）

- `src/jobagent/bridge/worker.py:163–185`：`_batch` 从 `SqliteOutreachRepository` 取 batch/approval，缺批准或原 ask 就拒绝；输入没有 Base、record、阶段、批准字段和来源版本。
- `src/jobagent/bridge/panel_decisions.py:96–123`：`asked_items` 从本地 `outreach_asks` 查待决定材料；未先建本地问题的共享记录不在该集合。
- `src/jobagent/storage/pipeline_proofs.py:189–210`：招呼结果证明继续要求本地原 batch 和 approval。

这些约束对现有本地模式有意义。共享环境接入若仅把飞书当展示层，表内真实本人批准仍可能无法进入该路径。修复方向是类型化接入原始本人决定与对应阶段材料，复用准确内容、目标、版本、查重等保护；不能要求本人再批准一次，也不能删除门禁或直接伪造一条本地本人决定。

## C2：本地 Pipeline 与共享 Schema 尚未映射（高）

- `src/jobagent/schemas/pipeline.py:25–35`：PipelineState 是 draft_pending/greeting_sent 等本地阶段，没有独立的共享批准字段。
- 同文件 `PipelineJob` 从第 70 行开始，第 74 行平台限定 boss/zhaopin。
- `src/jobagent/storage/pipeline_repository.py:34–56`：当前态读取固定来自 `pipeline_jobs`。

因此当前代码不能被描述为已经实现共享表两字段的联合状态机；尤其不能默认将共享阶段名称改成一个本地枚举就完成接入。先对照当前字段 Schema 和原业务协议生成版本化映射，覆盖可执行、无需动作、等待、终态与未知组合；审批阶段不能被独立字段解释。平台范围不兼容须显式报告，不把本地平台枚举当所有来源的业务限制。

## C3：本地动作回执不是共享业务回写完成（高）

`src/jobagent/bridge/worker.py:288–339` 的 `record_greeting` 在本地事务里追加审计、完成 claim 并产生 worker event；该路径不调用共享 Base，也没有共享记录写入及正向回读的证据。`WorkerSendReceipt` 在 `schemas/worker.py` 只保存本地 audit/event。

同文件第 341 行后的未知/不一致结果保护应保留。本地完成与外部动作回读仍可作为技术事实，但接入后必须分别记录“动作结果已核验”和“共享环境回写已核验”。后者失败时保留待回写与阻碍，不能据本地 completed 宣称业务闭环，更不能为补回执再次发送。

## C4：现有轮次报告不核对所有业务项的回写（中）

`src/jobagent/schemas/host_checks.py:23–36` 的 `HostRoundInput` 要求搜索 run_ids，unfinished 为宿主提供的字符串列表；没有本轮共享工作清单与逐项去向的覆盖证明。

`src/jobagent/storage/host_reports.py:234–247` 的 `core_ok` 检查实际查询、归因、页面和本地 pipeline 证明，未检查 unfinished 或共享回写。第 296 行只是保存 request.unfinished，第 300 行明确 `real_browser_verified=False`，所以不能把 core_checks_passed 解释为整轮业务完成。它是范围较窄的核心搜索检查，本轮不修改其含义或将其误报为已有测试失败。

合成复现：使用 `tests/storage/test_host_reports.py` 的 `round_evidence`，加入 `unfinished=["SYNTHETIC_BASE_WRITEBACK_PENDING"]` 后调用现有 `record`，得到 `core_checks_passed=true`、未完成项仍存在、`real_browser_verified=false`。这证明三个字段能同时成立，不能只展示第一个字段。

## 已落实的规范与后续代码任务

- `AGENTS.md`：共享来源权威、联合状态消费、每项去向、写入/回读、失败交代、待回写恢复和任务结果责任。
- `hosts/personal-ai/tasks.md`：设置任务时明确输入/动作/产物/回写/验收/失败/恢复，并回读实际任务正文；每轮逐项对账，无法写表仍须报告。
- 宿主入口及 memory 协议：本地存储限来源绑定的技术用途，不成为第二业务权威；已有本地命令的语义不冒充新接线。
- [实施任务单](../workflow-memory-implementation-plan-2026-11-19.md)新增 T0A，先完成共享状态类型、联合映射、来源验证、回写证明和覆盖核验，再接后续调度/Dream；没有把未来类型写成已存在能力。

无需为“防止漏写”给每段自然语言增加一套平行状态。宿主按明确任务结果执行并交代；代码负责可校验的来源、合法状态映射、版本冲突、幂等和覆盖。规范已修改不代表运行中的真实定时任务已更新。

## 验证

- 当前默认路径基线：`python -m pytest -q -x --tb=short`，176 passed / 1 failed，33.73 秒。失败仍为旧 MCP 只读 URI 路径问题，见[先前审查 R7](2026-11-19-workflow-memory-audit.md)。未改生产代码，不声明修复或全套通过。
- 上述 unfinished 合成复现已执行；不访问真实招聘账号或 Base。
- 本地代码专项：`python -m pytest -q tests/bridge/test_worker.py tests/bridge/test_panel_decisions.py tests/storage/test_host_reports.py tests/jobs/test_pipeline_contracts.py tests/storage/test_pipeline_proofs.py --basetemp .jobagent/shared-state-code-review-tests --tb=short`，154 passed，33.46 秒。验证的是既有本地路径，不证明新增共享接线已实现。
- 文档及目录：`python -m pytest -q tests/test_documentation_contract.py tests/test_skill_context.py tests/test_capability_status.py --basetemp .jobagent/shared-state-doc-review-tests --tb=short`，23 passed，4.89 秒。
- `python -m ruff check .` 通过；`python -m mypy src/jobagent` 通过（275 个源文件）；`git diff --check` 通过。
