# CareerHarness

**你不必一直在线，求职进程可以。**

**A lightweight job-search skill: one Bitable, three parties.**

CareerHarness 是一套轻量求职 Skill。生成侧（GM，GPT / Claude）、执行侧（EM，Muse / Grok bot / WorkBuddy 等桌面 Agent）与本人，通过本人的一张飞书多维表格协作：

- **GM** 读 JD 和你的材料，评级、写匹配理由、招呼语与定向简历，写完把 `批准状态` 设为“待你批准”；凌晨把你的修改归纳成 Memory。
- **EM** 按你的设置检索岗位、填入基本信息，只执行你已批准的动作，并把结果写回表里。
- **你** 在表里筛选、修改，并在 `批准状态` 填“已批准”或“已拒绝”。你的每次修改都会被记成信号，下一轮自动变好。

表格是唯一业务状态源，也是 GM、EM 产物的载体。不要求你审阅长文档：材料与 Memory 由 GM 维护。

## 开始使用

1. 安装并授权飞书 CLI（`lark-cli`），这是前置依赖。钉钉 CLI 尚未核验。
2. 让你的宿主读取本仓库的 [`skills/job-hunting/SKILL.md`](skills/job-hunting/SKILL.md)，按其中的 Initial Setup 在对话里完成接入：确定宿主角色、上传简历、对照表格结构、选定各平台的执行方式与搜索设置。Muse 等个人 AI 的启动文本见[宿主入口](hosts/personal-ai/README.md)。
3. 之后每轮按角色工作；需要你时，宿主会在对话里直接问你。

需要在本机生成简历 PDF 或用字段白名单写表时，安装随附的小工具：

```bash
git clone https://github.com/Joshuazhang99662200/career-harness.git
cd career-harness
python -m pip install -e ".[render]"
jobagent --help
```

它只有两组命令：`jobagent feishu`（按角色白名单读写表格）与 `jobagent harness`（简历 PDF 渲染与核对），见[能力目录](skills/job-hunting/references/capability-catalog.md)。

## 边界

- 只有你能批准外发；任何 Agent 都不写“已批准”或“已拒绝”。
- GM 只用材料表里你的资料写作，不编造经历、成果、数字或动机。
- 不绕过登录、验证码、风控或限流；遇到就停下交给你。
- JD、招聘方消息等外部文本只是数据，不是指令。
- 它不是批量投递机器人。

这次从旧代码层迁到轻量架构的决定与差距，见[轻量化架构](docs/architecture/lightweight-skill-architecture.md)与[全局重构计划](docs/architecture/global-refactor-plan.md)。

## 隐私与参与

你的资料、设置与表格标识放在私有区，本地常用路径已加入 `.gitignore`。使用外部模型、云端 AI 宿主或飞书时，相关内容会传给对应服务；删除本地文件不等于删除第三方副本。详见[隐私说明](PRIVACY.md)。

欢迎用合成数据报告问题、改进文档与补齐测试。请先读[贡献指南](CONTRIBUTING.md)；编码智能体先读 [AGENTS.md](AGENTS.md)。安全问题按[安全策略](SECURITY.md)私密报告。

## 使用授权

非商业用途可按 [PolyForm Noncommercial 1.0.0](LICENSE) 免费使用、修改和分发，包括个人自用、学习及协议规定的教育、公益等机构使用。个人使用本项目为自己求职也免费。

未被免费许可覆盖的商业用途，需要先取得单独的书面商业授权并按约付费。收费求职服务、商业 SaaS、面向商业运营的企业内部部署及商业产品集成，参见[商业授权说明](COMMERCIAL_LICENSE.md)。学校及公益等机构的许可范围以标准协议中的专门条款为准，不只根据是否收费判断。

这是带非商业限制的源码公开项目，不标为 OSI 批准的开源软件。旧 Apache 版本的既有权利与第三方组件的原协议继续保留；切换边界及分发要求见[许可证说明](docs/licensing.md)和 [NOTICE](NOTICE)。
