# 消费者依赖图与迁移依赖

基线：PR #36 head `f3eb022`。依赖关系由 AST 解析 `src/` 与 `tests/` 的 import 得出（516 个模块节点），再人工核对入口函数。箭头 `A → B` 表示 A 调用 / 读取 B。

## 1. 当前真实调用链

### 1.1 展示层：React / Console / MCP

```mermaid
flowchart LR
  React["frontend/ (React 19)"] -->|GET /api/snapshot, /api/definitions| Serve["jobagent console serve<br/>console/server.py (loopback GET)"]
  Serve --> Proj["console/projection.py<br/>snapshot() / definitions()"]
  CLIList["console list / definitions"] --> Proj
  MCP["bridge/mcp_server.py (stdio)"] -->|console_snapshot| Proj
  MCP -->|status_today / pending_approvals<br/>patrol_history / new_jobs| Status["bridge/status.py<br/>手写 SQL，无测试"]
  MCP -->|post / receipts / notes / peers| Mailbox["bridge/mailbox.py<br/>本地 jsonl"]
  Proj --> Outr["console/outreach.py"] & Assess["console/assessments.py"] & Pub["console/public_careers.py"] & Act["console/activities.py<br/>console-activities.json"]
  Proj --> DB[(SQLite)]
  Outr --> DB
  Status --> DB
  Pub --> DB
  Muse["frontend/src/muse (宿主面板组件)"] -.->|宿主适配器调用| Decide["console materials / decide / operation<br/>console host-state / selection / batch*"]
  Decide --> PD["bridge/panel_decisions.py"] --> OS["outreach/service.py"] --> DB
  Decide --> Exec["console/execution.py / selection.py"] --> DB
```

结论：React 与 MCP 共用 `console.projection`；MCP 另有 4 个工具直连 SQLite。**退役 Console 前必须先给 MCP 提供 Bitable 数据源**，否则 MCP 断裂。`bridge/status.py` 没有任何测试覆盖。

### 1.2 审批与执行：Worker / Outreach

```mermaid
flowchart LR
  Host["执行宿主 (Muse/Grok)"] --> WIngest["worker ingest"] --> W["bridge/worker.py"]
  Host --> WClaim["worker claim-greeting / authorize-greeting"] --> W
  W -->|当前共享记录| Reader["cli/worker._SharedReader"] --> GW["bridge/feishu_gateway.get"] --> Bitable[(Bitable Jobs)]
  W --> Gate["jobs/shared_send_gate.current_work_decision<br/>处理进度 × 批准状态"]
  W --> Fresh["bridge/greeting_freshness"] --> DB[(SQLite)]
  W -->|claim / audit / lease / event| DB
  Host --> WRec["worker record-greeting"] --> W
  W -.->|缺失：结果回写 + 回读| Bitable
  Approve["outreach approve / console decide / applications approve"] --> OS["outreach/service.py / applications"] --> DB
```

结论：只有 Worker 首条招呼的发送裁决消费 Bitable；其余审批命令仍写 SQLite 审批表，执行结果不回写 Bitable。

### 1.3 Search Plan / Fetch

```mermaid
flowchart LR
  SP["jobs search-plan"] -->|--memory-settings| RPM["bridge/preference_memory.refresh_preference_memory"] --> MD["私有 Markdown + history/"]
  RPM --> DB[(SQLite owner 事件)]
  RPM --> Codex["bridge/preference_reasoning → codex_runner"]
  SP --> PL["PreferenceLearner.select(task=search)"]
  SP -->|--search-memory| JSON["本地 PublishedMemoryFile JSON"]
  SP --> Apply["jobs/search_memory_apply"]
  SR["memory search-round / fetch-pin / fetch-continue"] --> SMS["bridge/shared_memory"] --> GW["feishu_gateway"] --> SM[(Bitable Search Memory)]
  SMS --> Round["memory/search_round"] --> Apply
```

结论：`search-plan` 与 `search-round` 是两条并行链；前者有三种 Memory 来源（无、Markdown、本地 JSON），后者只读 Bitable。目标是 `search-plan` 只走右侧链路并输出 Pin + Provenance。

### 1.4 Greeting

```mermaid
flowchart LR
  GG["greetings generate"] --> Ctx["bridge/greeting_context"] --> DB[(SQLite: candidate / evidence / jobs / outreach)]
  GG -->|memory_path 存在| RPM["refresh_preference_memory"] --> MD["私有 Markdown"]
  GG --> Dir["PreferenceLearner.direction"] & Sel["PreferenceLearner.select(task=greeting)"]
  GG --> Gen["bridge/greeting_generation → outreach/generation"] --> Codex["codex_runner"]
  GM[(Bitable Greeting Memory)] -.->|无消费者| GG
```

### 1.5 Dream / Signal

```mermaid
flowchart LR
  WF["Bitable Workflow (enabled=false 登记)"] -.-> HS[(Human Signals)]
  Page["memory workflow-page"] --> SMS["bridge/shared_memory"] --> HS
  Enrich["memory enrich-signal"] --> SMS --> Hist["feishu record-history → memory/history_match"]
  Start["memory dream-batch-start"] --> SMS
  GPT["宿主 GPT 推理 (host_delegated)"] --> Complete["memory dream-batch-complete"] --> SMS --> Pub["memory/publication + snapshot"] --> SM[(Search Memory)]
  Legacy["memory signal-receive / signal-compile"] --> Inbox["memory/signal SignalInbox (本地 fixture)"] --> JSON["本地 JSON"]
```

## 2. 迁移依赖图（必须满足的先后关系）

```mermaid
flowchart TD
  P1["P1 契约: StateMachine / SemanticMapping / Materials / SignalAssessment / MemoryRule / ChangeSet / Provenance"]
  P2a["P2 Gateway: create / 字段类型 / Schema Discovery → 映射差异"]
  P2b["P2 Initial Setup 命令 + 只读验收"]
  P3a["P3 状态迁移矩阵 + Jobs 读写服务"]
  P3b["P3 Worker 结果回写 + 回读"]
  P3c["P3 审批命令改读 Bitable 批准"]
  P3d["P3 MCP status / snapshot 改读 Bitable"]
  P4a["P4 SignalAssessment + disposition"]
  P4b["P4 Greeting Dream"]
  P5a["P5 旧 Memory 迁移工具 dry-run"]
  P5b["P5 search-plan → Bitable Search Memory + Pin"]
  P5c["P5 greetings / matching → Bitable Memory + Materials"]
  P5d["P5 Provenance 写 Jobs"]
  P6a["P6 退役 Console / Projection / Server / React"]
  P6b["P6 退役 status.py SQLite 查询"]
  P6c["P6 退役 MarkdownPreferenceStore / SignalInbox / SignalCompiler / P1 MemoryService"]
  P6d["P6 退役 SQLite 业务仓储与 migration"]
  P1 --> P2a --> P2b
  P2a --> P3a --> P3b & P3c & P3d
  P1 --> P4a --> P4b
  P2a --> P4a
  P4a --> P5a
  P3a --> P5b & P5c --> P5d
  P4b --> P5c
  P3d --> P6a & P6b
  P3c --> P6a
  P5b & P5c & P5a --> P6c
  P3b & P3c & P5d & P6a --> P6d
```

## 3. 高风险耦合点

| 耦合 | 位置 | 风险 | 处理 |
|---|---|---|---|
| MCP 依赖 Console Projection | `bridge/mcp_server.py:20-21` | 删 Console 会让 MCP 失去快照工具 | P3 先改 MCP 数据源 |
| `outreach/service.py` 被 16 个源模块引用 | patrol / pipeline_sync / job_intake_service / sent_tracking / conversation 等 | 审批与审计改动波及面最大 | 先抽出“读 Bitable 批准”的端口，再逐个替换调用方 |
| `storage.database` 被 64 个源模块、61 个测试依赖 | 全仓 | 一次性删库会让大量测试失效 | 按域退役，每域独立 PR |
| `schemas/preference_memory` 被 11 个测试引用 | G1 测试群 | 迁移 MemoryRule 时测试需要成对迁移 | 先建新模型与转换函数，再迁测试 |
| `greeting_context` 直读 candidate / evidence / outreach 表 | `bridge/greeting_context.py` | Materials 迁移依赖它 | 引入 `MaterialsReader` 端口 |
| Candidate Evidence 硬性边界 | `CandidateEvidenceService.confirm` | 存储迁移不得绕过唯一提升入口 | 见审计 §5.1 |
| `cli/jobs.py`（1269 行）同时承载 search-plan 三种 Memory 来源 | `cli/jobs.py:703-814` | 切换时容易残留 fallback | P5 删除 `--memory-settings` / `--search-memory`，Memory 不可用即报错 |

## 4. 无消费者 / 孤立项

- 表 `outreach_audits_next`：migration 0011 创建，无任何代码引用。
- `bridge/sourcing_feedback.py`：无 src 消费者、无测试。
- `bridge/codex_reasoning.py`：无 src 消费者，仅 1 个测试。
- `memory/search_round.py`：无直接测试（经 `shared_memory` 间接覆盖）。
- `bridge/status.py`：仅 MCP 使用，无测试。
