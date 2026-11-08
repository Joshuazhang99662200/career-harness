# Muse 通用 React 模板

业务展示与交互统一按[当前面板要求](../docs/muse-panel.md)执行；视觉以同版本代码为准。

仓库只保留一套前端：默认页面合并自真实面板代码包（2026-11-06）的框架。批准与执行分开、只执行已批准材料等前提不变，见[合并记录](../docs/muse-space-template-2026-11-06.md)。详情、审阅、独立待办、执行清单，以及运行记录、沟通进展、公开职位补充和数据说明页均可交互。上一版分享页还原（`?template=current`）和兼容 Console（`?legacy=1`）已于 2026-11-08 移除。

默认入口 `?demo=1` 使用合成数据；不带参数时读取真实来源，来源失败不会自动进入演示。

```powershell
npm.cmd ci
npm.cmd run typecheck
npm.cmd run build
npm.cmd run test:ssr
npm.cmd run dev -- --port 5178
```

独立页面输出 `dist/`；Muse 库输出 `muse-lib/`，类型声明输出 `lib/`。字段类型通过 `python scripts/build_muse_contracts.py --check` 核对 Python 权威传输模型。

```tsx
import { MusePanel, type MuseActions } from '@jobagent/polling-console/muse';
import '@jobagent/polling-console/muse/styles.css';

<MusePanel actions={hostActions as MuseActions} cvFiles={hostPreviewFiles} />
```

宿主提供 `MuseActions`，或向 `MuseSourcePanel` 注入已有 `ConsoleDataSource`。查看与筛选不执行招聘操作。真实保存、审批、发送与回读必须调用已有业务服务。未接入的能力要禁用或明确说明，不能用前端状态变更代替成功。

`MusePanel` 可选 `publicCareers` 读取函数；`MuseSourcePanel` 从数据源快照中读取公开职位补充。未提供时，该页显示“公开职位补充尚未接入”，不显示为没有岗位。

样式限定在 `.muse-space`。Muse 样式包适合独立面板；宿主需要完全隔离样式时在 iframe 内挂载。React 和 React Query 作为 Muse 库的外部运行时依赖；分发构建资产时保留 `THIRD_PARTY_NOTICES.md`。

## 2026-11-03 同步增量

默认模板新增统一渠道标签、常驻选择队列、仅消费已有准确批准的快捷执行、重新生成与改写记录、失败累计与本人重试，以及完成结果归岗位进展。详见 [增量合并核对](../docs/panel-sync-merge-2026-11-03.md)。

`MusePanel` 的完整动作接口已包含同步包新增 RPC；`MuseSourcePanel` 可接收 `syncActions` 注入真实服务。缺少服务端选择接口时禁用选择；重新生成须同时提供生成与改写记录查询，未接通时明确禁用。重新生成只有在宿主记下改前与改后全文、并与当前稿一致时才显示成功；生成期间正文不可编辑；新稿会使旧批准失效。默认 demo 的选择存储只是合成演示，不能当作服务端持久化验收。

快捷执行不为未审阅材料自动批准，失败项保留在选择队列；结果未知不能重试。只把正向回读成功的岗位移出已选。完成后只留批次汇总，逐项结果在各岗位进展与历史中查看。

## 构建和运行

需要 Node.js 22.12+ 和已配置的 Python 项目环境。在本目录执行：

```powershell
npm.cmd ci
npm.cmd run build
```

回到仓库根目录，按 `jobagent console serve --help` 指定候选人、数据库、工作区及静态目录 `frontend/dist`。启动参数详见仓库 `docs/polling-console.md`。

开发预览运行 `npm.cmd run dev`。明确使用 `?demo=1` 才会显示合成示例；真实查询失败不会自动改成示例。示例快照和字段契约由仓库的 Python 生成脚本导出，不能手工改成另一套领域模型。

页面刷新只重新读取本地快照，不会改变轮询频率、读取额度、平台状态、动态参数或任何业务记录。更新前端构建后，已打开的页面需要重新加载才能使用新代码。

## 验证

```powershell
npm.cmd run typecheck
npm.cmd run build
npm.cmd run test:ssr
# 使用 Playwright 已安装的浏览器，或者显式指定本机 Chromium / Edge：
$env:CONSOLE_BROWSER = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
npm.cmd test
```

`tests/muse-space.spec.ts` 与 `tests/muse-space-rules.spec.ts` 覆盖默认面板的产品规则，包括：

- 批准不等于发送；
- 改稿后必须重新批准；
- 猎聘不显示招呼语步骤；
- 已发送正文只读；
- 已关闭岗位不标“现在”；
- 公开职位补充区分“未接入”“读取未完成”和“已完成且无岗位”；
- 来源失败时不回落演示；
- 390px 下无横向滚动。

`tests/muse-regeneration.spec.ts` 用注入的合成宿主核对重新生成。测试只使用合成数据。

## 宿主交互接口

接口、接入边界和逐项验收见 [宿主接口说明](../docs/react-console-host-interface.md)。共享传输类型从 `src/jobagent/schemas/console_host.py` 生成：

```powershell
python scripts/build_console_host_contracts.py
python scripts/build_console_host_contracts.py --check
```

## 使用授权

组件源码使用 [PolyForm Noncommercial 1.0.0](../LICENSE)：非商业用途免费，商业用途须按[商业授权说明](../COMMERCIAL_LICENSE.md)另行取得授权。教育、公益等机构按标准协议专门条款处理；旧版 Apache 既有权利和第三方依赖协议保留。`npm run build` 会将项目法律文件及 `THIRD_PARTY_NOTICES.md` 一并复制到 `dist/`、`lib/` 和 `muse-lib/`，分发时须保留。
