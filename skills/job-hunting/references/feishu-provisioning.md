# 飞书自动配置

此流程由 [Initial Setup](first-use.md) 调用，适用于首装、接入另一宿主和 Schema 漂移后的修复。唯一字段与信号清单是 [飞书 Schema](feishu-schema-bootstrap.md)。使用官方 lark-cli 获取实表状态，`jobagent setup feishu-plan` 将结果转为本阶段的动作。输入、输出和临时文件留在私有目录。

## 授权与发现

1. 先验证官方 CLI 与用户身份。没有授权时将 `auth_verified` 保留为 false。用户同意自动配置时设置 `configure=true`，同意新建工作区也设置 `create=true`。同一次授权可明确允许为此 Base 的既有注册 Bot 授予编辑权限。已有私人设置继续使用。
2. 有已绑定 Base 或用户明确指定 Base 时，先用 `base +base-get` 验证目标，读取表和字段，绑定放 `bound_base`。可用 `base +url-resolve` 从飞书链接取得坐标。恢复路径优先依据指定绑定；访问异常时保留原绑定并报错。
3. 未绑定时，以当前用户身份用 `drive +search --doc-types bitable --mine --as user` 查找 CareerHarness，并遍历本人拥有的 Base 识别旧名称的兼容工作区。通过 `--page-token` 跟随 `data.has_more` 读完 `data.results`。以 `result_meta.owner_id` 对应本次授权身份、`base +base-get` 可访问且 Schema 签名匹配为依据。签名要求岗位表同时有 `岗位ID`、`批准状态`、`Muse处理`、`GPT处理`，另至少存在一个其余业务表。中断恢复时接受名称恰为 CareerHarness 且含正确岗位主字段的部分 Schema。用户提供的已共享 Base 单独验证后可绑定。同名但结构无法证明归属时保留为冲突候选。分页、ACL 或搜索状态无法确认时不得把空结果交给创建步骤。
4. 将确认过的候选写成 `candidates=[{base_token,name,owned,recognized}]`。确认所有页后才写 `discovery_complete=true`。同一 Base 多次出现按真实 token 去重。多个可信候选时两端均停止写入，由用户选一个已验证的 Base。先选、再存 `bound_base`。跨宿主使用相同所有者及 Schema 签名查找，各自管理授权和私有配置。
5. 新建前立即再发现一次。宿主有共享初始化互斥时持有到最终绑定。没有跨主机互斥时，先私有记录 `creation_pending=true`，再创建一个带完整岗位首表的候选。收到 ID 即存为私有 `created_base`。重新完成所有者和签名发现，创建候选只在成为唯一可信候选后进入补齐。如果有目录读权限，用 `drive files list --as user` 复查创建目录里的同名 Base，补偿索引延迟。最终绑定前再次核查，看到多个候选立即停在冲突。飞书 Base 创建没有原子唯一命名。对账无法完成、API 结果不明或并发归属未明时，保留私有待核验状态，禁止盲目重发创建。已有主机可继续使用先前已绑定的 Base，新宿主不自动发布第二份工作区。

## 对账与执行

在有安装包的宿主运行 `jobagent setup feishu-plan --contract <feishu-schema-bootstrap.md> --request <私有快照文件>`。角色加载之前执行。私有快照只写本轮实测值：

- `observed_base` 是本轮实际读取的目标。用 `base +table-list` 和每张表的 `base +field-list` 按 `--offset`/`--limit` 读完，把真实 `tables=[{id,name,fields}]` 放入快照。字段条目使用 `id`、`name`、`type` 等 CLI 原字段；单选保留 `multiple`、`options`、`default_value` 等属性。
- 未绑定且完整发现后，`provision` 返回一次首表创建。按计划实际执行下表的动作。动作返回后回读并重新生成计划。实表读取完整以前不传空列表。字段缺失则补建；已有顺序、额外字段和附件保留。同名不同类型、多选或动态选项冲突直接报告，无自动迁移。
- 写入响应检查真实业务成功、结果数量与目标关联。先完成本阶段独立动作再读回已知资源，禁止用计划值替代返回的 ID。结果不明先核实实际对象，不能证明结果时停止对应操作。已有 Base 工具不支持发现或 Workflow 管理时，报告缺失命令或权限；先检查已安装官方 CLI 帮助和受支持 API，再继续。
- `field-update` 是全量 PUT。执行前用 `+field-get` 读取完整当前定义，检查计划依据仍一致，保留所有现有可写属性和选项 ID、颜色、顺序及名称，仅追加缺项。CLI 的高风险确认走用户已授权且目标明确的追加操作；如无法保留定义则停止。
- Schema 完整后验证同一个注册 Bot 能访问 Base、按 GM/EM 白名单读写岗位以及履行本宿主角色需要的材料权限。权限不足时，持有用户明确授权与已确认的同一个应用 App ID，可用 `drive +member-add --type bitable --token <base> --member-type appid --member-id <已注册App ID> --perm edit --as user`。先用 `--dry-run` 核对对象、权限和范围，再用 `--yes` 执行并读回。应用或权限无法确定时交给用户处理。用户授权合成行写入和清理后，用 `--as bot` 做可回读的小测试。只在有验收记录后设置 `bot_can_write=true`。
- 用 `base +workflow-list` 读取 `data.items`，逐个 `+workflow-get` 读取 `data` 中的状态与步骤，传 `workflows=[{workflow_id,title,status,steps}]`，全量读取才置 `workflows_complete=true`。旧的全角色监听只做迁移检查。本人授权停用时才设 `disable_legacy_trace=true`，按计划停用核实的 CareerHarness 监听并读回。发现错误引用、重复监听或未知定义时报告冲突，由本人确认目标。

| 计划动作 | 官方 CLI 参数 |
|---|---|
| `+base-create` | `base +base-create --name <target> --table-name <table> --fields <payload>` |
| `+table-create` | `base +table-create --base-token <base> --name <table> --fields <payload>` |
| `+field-create` | `base +field-create --base-token <base> --table-id <target> --json <payload>` |
| `+field-update` | `base +field-update --base-token <base> --table-id <真实表ID> --field-id <target> --json <保留属性后的完整定义> --yes` |
| `+workflow-disable` | `base +workflow-disable --base-token <base> --workflow-id <target>`，仅限本人授权停用的旧监听 |

管理操作在末尾加 `--as user`。结构化参数用 argv 或官方 `@file` 形式传递，避免 Windows shell shim 损坏 JSON。已有 `jobagent feishu schema/query/get/patch/record-history` 继续使用私有 `FeishuConfig` 和官方 CLI 原生可执行文件。

## 验收与绑定

1. 使用经本人授权且无招聘方关联的合成行核对 Bot 的角色字段白名单与实际读回。测试的批准列仅允许用 GM 可写的 `待你批准`。按授权清理本轮合成数据，写入或清理结果不明时先读回。
2. Base 与必要角色权限通过后，返回 `status=ready`。在私有 `settings.json` 保存实际 `binding`、身份、验收时间与 [共享飞书环境](feishu-shared-source.md) 需要的字段映射。
3. Trace 用 [仅本人修改触发 Human Signals](human-signal-capture.md) 独立验收。角色过滤、真实事件订阅和受信任接收宿主均验证后才设 `native_trace_verified=true`。旧的 `verified_workflows` 回执不代表原生链路就绪。以最新 `trace_status` 报告迁移、冲突或待接入情况，业务任务范围仍取决于其自身前置条件。
4. Dream 由宿主调度，实际运行通过才设 `dream_verified`。后续启动分别核对业务字段、原生事件和接收宿主状态；配置变化时重新核验对应层。
