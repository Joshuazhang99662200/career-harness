# 招聘平台能力路由

先在 [Initial Setup](first-use.md) 中完成飞书绑定。本人选择平台和业务条件，宿主自动寻找并核验入口。

## 展示与保存本人的选择

| 平台显示 | 私有配置键 | 岗位表枚举 |
|---|---|---|
| BOSS 直聘 | `boss` | BOSS |
| 猎聘 | `liepin` | 猎聘 |
| 智联招聘 | `zhaopin` | 智联 |
| LinkedIn | `linkedin` | LinkedIn |
| 企业招聘官网 / ATS | `ats` | ATS |
| 小红书 | `xiaohongshu` | 小红书 |

平台可多选、跳过或以后修改。显示「已验证可用」「需要登录」「需要授权」「待验收」「当前宿主不支持」或「受限制」，每项按本宿主验收记录展示。跳过保存空列表，尚未回答保留 null。已确认的选择由 GM-first 和 EM-first 共用，包括跨宿主接入。若另一宿主读不到同一份私有偏好，由用户授权传递已确认选择；不能把技术状态复制成已验证。支持用户在任一宿主更新偏好，并同步本人明确授权可共享的私有选择。

## 探测和验收

1. 枚举当前宿主实际提供的 Browser GUI、Chrome 插件、云浏览器、平台 MCP/Helper 和官方 CLI。检查入口对该平台的真实支持、当前登录、搜索授权及后台能力。用户明确禁用的路径不探测。
2. 在授权范围内访问平台，用有界只读抽样验证能打开列表、读取完整 JD、分页/翻页（只出现一页时需核查明确的末页），并记验收记录。平台限制或登录失效时停止当前操作。禁止用安装状态代替访问验收。搜索途径验收与平台后续操作验收分开。后续执行权限、具体对象和材料在实际批准后复核，Setup 不发送消息或投递。
3. 按平台和入口记录 `probes`：`{platform,kind,endpoint,host,session,available,login,search_authorized,list_verified,jd_verified,page_verified,background_verified,scheduled_authorized,execution_verified,restricted}`。入口类型是 `browser_gui`、`chrome_plugin`、`mcp`、`cli` 或 `cloud_browser`，`endpoint` 为宿主私有工具定位值。公开站点可把无须登录且已成功访问记为 `login=ready`。后台能力须在实际后台环境验证。记录授权验收记录、时间和失败原因供下次复核。
4. `session` 随新宿主进程、权限变化或受限失败作废，重新探测后才进入下一轮。路由要求 `host` 与当前 `session` 都一致。仅用已验证的路径。运行中遇到 CAPTCHA、风控、限流、登录失效或页面限制，记录平台级阻塞，当前轮停该平台，继续其他就绪平台。任何切换须经过新的授权与验证，且不得绕过阻塞。

## 选择执行路径

将私有设置、探测结果与运行条件一起传给 `jobagent setup platform-routes --request <私有请求文件>`，请求形状为 `{settings,probes,host,session,mode}`。首次展示平台时可用六个平台进行预览，预览不写入用户选择。执行时只用用户明确选择的集合。

- 交互式 `mode=interactive`：优先已验证的本地 GUI 或 Chrome 插件，之后比较 MCP、CLI 和云浏览器；无 GUI 环境使用已验证且授权的 MCP/CLI 等可用入口。
- 定时 `mode=scheduled`：仅接受经后台实测且有定时授权的入口，同时需要已确认日程、该平台配额与硬筛条件（可明确确认无硬筛）。无可用路径就报告 `no_background_route`。
- 默认 `routing_mode=auto`。仅用户主动覆盖时设 `override` 并持久化指定方式。覆盖不可用就显示原因。禁止方式优先于覆盖与自动决策，云浏览器仍需该方式自己的授权。
- 当前平台的 `unsupported`、`restricted`、`needs_login`、`needs_authorization`、`needs_probe`、`unverified`、`forbidden`、`override_unavailable` 或 `business_settings_pending` 仅作用于对应平台。EM 汇报时区分这些状态。用户选择平台允许搜索与准备材料，每次外发仍以最新表内本人批准、有效材料与已授权执行路径为前提。

## Memory 如何进入搜索

- `rank_candidates`：GUI 用平台自身推荐、搜索结果与岗位详情取得候选，避免固定词裁剪发现范围；Search Memory 用于软偏好判断、重排序和入库取舍。
- `query_then_rank`：MCP/CLI 根据已确认的求职方向、本人硬筛与 Search Memory 生成检索词和查询参数，再按同一版本 Memory 匹配与重排。对软偏好保留可探索的查询分支。
- 两种方式都单独保留本人确认的硬筛，只使用其业务条件作为必排规则。临时负面信号和一次未批准只影响相应情境，不能升级为永久排除条件。

## 私有 settings.json

保存 `recruitment_platforms` 段，保留原有无关键。业务字段为 `selected`、`routing_mode`、`overrides`、`prohibited`、`per_platform_quota`、`total_quota`、`schedule`、`hard_filters`。未确认日程、配额与规则保留空值或缺项，明确无硬筛可保存空对象。把确认过的旧平台选择、用户明确指定的选项和限制迁到对应键；旧技术状态要重新验收。当前入口、交互与定时分别可用的状态、时间及授权验收记录放当前宿主的私有段，按 `host` 与 `session` 区分。路由和测试通过不写任何招聘审批或回执。
