# 贡献指南

## 环境

需要 Python 3.11+。

```bash
python -m pip install -e ".[dev]"
```

## 质量门禁

提交前按顺序跑完这四条,全部通过才算完成:

```bash
python -m pytest -q
```

```bash
python -m ruff check .
```

```bash
python -m mypy src/jobagent
```

```bash
git diff --check
```

mypy 配置为 `strict`。Ruff 行宽 100,启用 `E,F,I,UP,B,SIM,RUF`。

## 测试驱动

本项目采用测试先行:先写失败的测试,确认它以预期原因失败,再写实现。测试不是补交的证明材料,而是设计工具。

每个能力都要有独立测试。

## 不可违反的架构不变式

```text
Bitable is the only business state
Only the person approves
Generation != Execution
Materials != Memory
Approval != Send
CAPTCHA != Retry
```

具体到代码与文档:

- 能用多维表格、官方 CLI 和已有实现做到的就复用；规则优先写进角色 md 与 Skill reference，不另起炉灶写代码。
- 仓库代码限于首次配置对账与角色及事实路由（`jobagent setup`）、本人 Trace 规划与表格字段白名单（`jobagent feishu`）、简历 PDF 渲染核对（`jobagent harness`）。实际变更由官方 CLI 和宿主工具执行。
- [本人 Trace 契约](skills/job-hunting/references/human-signal-capture.md) 要求先验证原生事件中的本人身份，再查询或写入 Human Signals。Bot 写入只提供基线，旧的全角色监听只能按授权迁移停用。
- 任何 Agent 都不写“已批准”/“已拒绝”；GM 对批准字段只能写“待你批准”。
- 领域模块不得 import Typer、浏览器自动化、DOM 选择器或平台 SDK。
- 遇到登录、CAPTCHA、验证、风控、平台变更就停下交给本人，不得绕过或自动重试。

违反上述任意一条的 PR 不会被合并,无论测试是否通过。

## 新增或删除命令

先写失败的测试，再实现；同时更新 `skills/job-hunting/references/capability-catalog.md`。`tests/test_capability_status.py` 会双向断言目录中的命令集合与 Typer 实际命令树完全相等,漏更会直接失败。

## 文档语言约定

- 面向人的文档(README、`docs/` 顶层、`skills/job-hunting/**/*.md`)用**中文**。
- 代码、注释、docstring、测试名、提交信息主题行之外的标识符用**英文**。
- 技术标识符在中文行文中保持原样:schema 类名、字段名、CLI 命令等。
- `docs/superpowers/` 下的 specs 与 plans 是带 commit 哈希的历史评审记录,**保持英文原样,不要翻译**。
- 两个 `SKILL.md` 的 frontmatter `description` 采用中英并列,以兼顾中英文查询的技能命中率。

## 提交与 PR

### 贡献的授权边界

项目采用 [PolyForm Noncommercial 1.0.0](LICENSE)，并提供独立的[商业授权](COMMERCIAL_LICENSE.md)。参与前先读[许可证说明](docs/licensing.md)。

贡献者保留自己贡献的著作权。引入外部贡献前，维护者须另行取得足以同时提供非商业和商业许可的明确授权；仅依赖 PolyForm 的非商业许可、提交 PR 或点击合并，不视为完成这项授权，也不视为著作权转让。没有确认授权范围的贡献，不纳入需要商业授权的分发。

第三方内容须保留原许可证、署名及 notices；不能因为本仓库更换协议就改变它们的权利。商业授权也不能替第三方授予本项目无权授予的许可。

- 提交信息用 Conventional Commits 前缀(`feat:` / `fix:` / `docs:` / `test:` / `refactor:`),正文说明**为什么**,不只是改了什么。
- 一个提交一件事。不要把无关改动混进来。
- PR 中附上改动文件清单、测试证据,以及一句架构不变式自查结论。

## 绝对不要提交的内容

真实简历、真实联系方式、`.env`、数据库、浏览器配置、会话令牌、私有 `settings.json`、Base / 表 / 字段或 Tunnel 标识、生成的简历变体。这些路径已在 `.gitignore` 中,但请在 `git add` 前自行确认。复现问题时一律使用合成数据。

## 不会被接受的贡献

- 绕过平台登录、验证码、风控或反爬机制的代码;
- 移除或弱化人工审批门禁的改动;
- 把本项目改造成批量自动投递工具的方向性改动;
- 未经许可证核查就引入的上游代码——先更新 `skills/job-hunting/references/oss/source-manifest.yaml` 与 `docs/oss-review.md`。
