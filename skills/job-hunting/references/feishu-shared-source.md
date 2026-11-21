# 共享飞书环境：两侧共用的最小调用协议

在读取共享岗位待办、生成侧回填或执行侧回写时加载本页，再读能力目录；无需预读全部宿主和 Memory 文档。三方是生成侧、执行侧、人类；Muse/GrokBot/WorkBuddy 是执行侧的可替换宿主。

## 当前可调用范围

`jobagent feishu schema/query/get/patch` 共用 `FeishuConfig` 和实时字段映射，不创建 SQLite、业务队列或全局消费游标。生成侧查询待评估范围，执行侧联合查询批准与进度；实际动作仍按既有业务协议进行。字段条件由已确认配置/业务 Schema 提供，查询返回不授予发送权。

`patch` 当前只支持普通 text/select 字段；本人决定字段不可写，附件使用专用能力。已批准材料不能原位改写，也不会自动重置批准状态。新版本材料及重新审批仍按业务协议处理，不能因本地缺批准记录要求重复批准。

## 接入前核验

1. 首先运行 `lark-cli.cmd auth status --json --verify`（Windows），复用现有授权。状态检查与实际调用都须成功；沙箱无法访问本机凭据时使用宿主允许的正常凭据环境，不因此重新初始化或登录。
2. 按 `lark-base` 技能通过已配置的 CLI/MCP 读取真实表和字段；配置只保存 Base/表/字段坐标、明确操作身份和角色白名单，不保存 access token、appSecret 或登录凭证。
3. `FeishuConfig` 放本人的私有工作区。`executable` 指向已安装官方 CLI 的原生可执行文件。Windows 的 npm `.cmd` shim 会破坏部分 JSON 参数的引号，本适配器拒绝 shell shim，直接以独立 argv 调用其原生二进制；不调用 shell、不下载或安装程序。
4. 新宿主分别核验“可读取来源、可运行相同 CLI/runtime、使用同一字段语义和相同角色权限”。本机成功不代表云宿主能访问本机文件、凭据或命令。

以下只是合成配置形状，所有 ID/选项都必须换成实际读取且确认的配置，不是个人默认：

```json
{
  "base_token": "BASE_SYNTHETIC",
  "identity": "user",
  "executable": "/installed/native/lark-cli",
  "timeout_seconds": 30,
  "tables": {
    "jobs": {
      "table_id": "tblSynthetic",
      "fields": {
        "assessment": "fldAssessment",
        "progress": "fldProgress",
        "approval": "fldApproval",
        "greeting": "fldGreeting"
      },
      "writable": {
        "generation": ["assessment", "greeting"],
        "execution": ["progress"]
      },
      "material_fields": ["greeting"],
      "approved_values": ["APPROVED_SYNTHETIC"]
    }
  }
}
```

`timeout_seconds` 是传输超时，示例不确定本人业务频次/Batch Size。`identity=user` 的 AI 操作仍可能在飞书历史中显示为本人身份，不能据此推断本人偏好或批准；来源归因需另外核验。

## 生成侧与执行侧查询

两侧使用同一 `FeishuQuery`，显式传本次取数上限，复用已有确认资源参数，不生成新的默认。

生成侧的合成查询示例：

```json
{
  "table": "jobs",
  "fields": ["assessment", "progress", "approval"],
  "conditions": [["assessment", "empty"]],
  "limit": 2,
  "offset": 0
}
```

执行侧使用同一结构，条件为 approval 与 progress 的联合 AND；具体可执行选项来自既有业务 Schema，不将所有已批准记录都当可发送。这里的 2 仅为合成演练样例，不激活本人 Batch Size。

```text
jobagent feishu schema --config <private-config.json> --table jobs
jobagent feishu query --config <private-config.json> --request <query.json>
jobagent feishu get --config <private-config.json> --table jobs --record-id <record-id>
```

安装包中通过 harness bootstrap 调用上述命令，不依赖开发者的全局命令。

`has_more=true` 时只证明当前页已读取；继续同一查询需使用 next_offset，并传 expected_table_revision。版本变化会报错，应重新读取当前范围并对账，不宣称遍历完成。offset 和原生页版本只用于这次遍历，不是跨周期业务检查点。下一轮重新按业务条件查询，未处理记录继续留在原待办范围。

## 明确字段回写与核验

从 `get` 取完整映射内容摘要后准备 `FeishuPatch`：

```json
{
  "table": "jobs",
  "record_id": "recSynthetic",
  "role": "generation",
  "expected_digest": "sha256:<exact-get-result>",
  "fields": {"assessment": "Synthetic grounded result"},
  "evidence_reference": "SYNTHETIC_REVIEW_1"
}
```

```text
jobagent feishu patch --config <private-config.json> --request <patch.json>
```

只写显式字段，不改其他字段；先核对 live Schema、角色白名单与写前摘要，再更新并读回准确值。角色参数是宿主调用约束，不是飞书身份认证或本人批准证明。`evidence_reference` 保留宿主提供的引用，不代表已验证平台动作。

- `verified`：所请求字段的正向回读一致；不证明已发送或全部业务完成。
- `unverified`：字段被忽略或回读不一致，不能当成功。
- `unknown`：派发/回读出错，先核验，不自动重复写入或外发。

内容摘要标记为 mapped_content_sha256，绑定当前配置映射的内容，不是飞书原生记录 revision，也不是原子 CAS。写前读取与实际写入之间仍有并发窗口；多个写者需要宿主按既有共享协调协议处理。本适配器不能独立证明批准材料新鲜度、平台查重、真实发送或合法阶段迁移。

## 记录历史与事件

生产人工信号来自私有 `FeishuConfig` 里登记、且保持 Disabled 的三条 Workflow。表 ID、Workflow ID 和字段 ID 都来自首次接入时读到的本人 Base，代码不写死某一张 Base。记忆配置必须映射 Jobs、Materials、Human Signals、搜索记忆和招呼语记忆；旧 Records 活动表不是 Human Signals，不作为这项配置的必需表。Materials 保留。三条 Workflow 只在 Human Signals 表追加一行，写入 `source_table`、`source_record_id`、`job_title`、`field_name`、`field_id`、`signal_type`、`memory_domain` 和 `learning_status=pending_history_enrichment`。该行的 record_id 是唯一标识。`memory signal-receive` 只解析本地 `drive.file.bitable_record_changed_v1` fixture，不是生产入口。本仓库不提供建表、改字段类型或启用 Workflow 的命令。

Dream 写入搜索记忆时，`jd_digest` 是来源岗位 JD 正文的摘要。只有一个来源岗位时，它等于该正文的 `text_digest`。多个来源岗位时，它是这些岗位 record id 及其 JD 摘要的来源上下文摘要。它不是关键词、方向或排除项对象的哈希。来源岗位没有 JD 正文时拒绝发布，不编造摘要。

`jobagent feishu record-history` 对一条岗位记录调用官方 `base +record-history-list`，不遍历全表历史。只有整段历史里该字段恰好一次可读的 before/after，并且操作者能用 open_id 或 union_id 唯一对照名单时，结果才是 matched。仅有显示名、名单对不上、前后值不唯一，都是 unknown，不猜测，也不把 Bot 写成人工偏好。历史没有读完时直接失败，不把不完整结果当成 unknown 后推进状态。

`pending_history_enrichment` 只在状态回写正向核对后改为 `pending_dream` 或 `unknown`。查询失败或回写失败保持原状态。`learned` 只在调用方交来的记忆草稿完成版本写入和回读之后更新。Dream 仍由 GPT 执行，本适配器不调用模型。

事件订阅仅提示对应宿主刷新当前记录；各侧仍按业务条件重新查询。不能把 CLI 事件目录的空缺写成平台没有该事件，也不能虚构 event consume 命令。官方 SDK 的长连接路线见 [Node SDK](https://github.com/larksuite/node-sdk)。本页不证明事件长连接已经启用。

## 可用性验收

先用合成 transport 验证两侧相同字段映射、联合条件、分页、陈旧版本拒绝、角色越界/代批拒绝、选项校验、错误/未知结果及正向回读。再对本人指定的合成记录进行两侧读写与历史回读；新增记录及真实写入须取得对应授权。

宿主实际启动、浏览器操作、事件唤醒、Dream 和招聘发送分别验收。记录每层的实际结果和未接通项，不能把在本地以两个角色调用成功写成两个独立宿主已接通。
