# Quality review: fact gates, relevance and expression

Check facts first, then quality. **Fluent writing never lets an unsupported claim through.** If an independent reviewer is available, start a separate review task and give it only the same original inputs, the message and the declared fact references, not the drafter's self-scores. Otherwise run a self-check and label it `self_check` honestly.

Review results are notes for GM, not a stored contract. Record the failure label, the exact passage and the reason; whether the draft goes out is decided only by the person in `批准状态`.

## A. Hard gates (any failure → revise or block)

1. Is the key JD content actually visible? Is a partial JD labelled as partial, not passed off as full text?
2. Is every person, project, responsibility, skill, result and metric supported by supplied facts? Is any substantive claim in the message missing from the list of facts cited?
3. Has a JD requirement been turned into the candidate's experience, or thinly documented work promoted to a validated result?
4. Are corrections, ownership, individual contribution, metric definitions, dates, offline vs online, and confidentiality all preserved?
5. Are this request's language, channel and explicit user constraints respected?
6. Is there any implication of sending, approval or external action?

If a gap affects only some sentences, delete or narrow those sentences. If the only main line cannot be supported, return `need_materials`. Do not cover the gap with nice wording.

## A2. First-contact overproduction and whole-message coherence gate

这是事实接地之后可否决草稿的沟通质量门禁，适用于所有职业。语言流畅、术语专业或命中JD关键词都不足以单独通过。

通读整篇，检查以下问题：

1. **未核实的用人方猜测：**断言或预设JD及授权来源没有确认的产品缺陷、团队优先级、用户问题、路线图或执行选择。
2. **方案过度生成：**提出无助证明既有能力的未来功能、工作流、策略或运营决策。“希望”“意向”“观点”等语气不能免除检查。
3. **把JD复述当洞察：**没有真实历史贡献支撑，却把用人方期望成果改成候选人的个人思考。
4. **猜测挤占事实：**推演占据篇幅，反而遗漏最有说服力的材料事实、取舍、贡献或结果。
5. **语段拼接：**句子各自有力，但项目、主语、主张和因果无法形成一条可读主线。不能分别给段落高分再加总判通过。

失败时，引用触发问题的原文连续片段，并给出可执行修改，通常优先删除该片段，再通读整篇。不要要求换成另一条行业观察、新功能或额外成果。问题片段主导全篇时，重组主线，不能只补一句转场掩盖。

**判定：**无用猜测、JD复述伪装洞察、过度方案或拼接判为表达不通过；用人方猜测或错误业务前提进一步扭曲能力证明时，同时判为偏离岗位核心。只有整篇通过时才判通过，不能只因事实有来源就放行。

**不应误判：**简短礼貌意向、有真实工作支撑且确有解释增量的专业判断、完全没有用人方方案的正文、只覆盖一项相关经历的简短完整消息。不存在必须展示最低数量产品洞察的要求。

**删除后再检查：**这句消失是否削弱能力证明？没有削弱则优先删除。继续检查剩余语句能否自然承接，不要求补一句替代内容。

## A3. 事实深度与三类问题分开复核

独立Reviewer须对照原始JD、同版本材料 md、正文及其主张回答：

1. 核心能力是否有真实工作情境和个人贡献支撑？材料提供了具体经历却只写职务或工具列表，记`depth_collapse`；寻找同一项目可恢复的关键行动、选择或验证，不要求增加其他项目。
2. 情境、行动和验证是否连成主线？各段真实但互不承接，记`narrative_collage`；选择主线并重写全文，“此前、后来、同时”不能代替有依据的因果或迁移关系。
3. 是否把未知的招聘方业务、路线或方案写进正文？记`unsupported_target_projection`；删除无依据推演，不要求另一个洞察补位。

高影响问题判为表达不通过，严重偏离岗位核心时同时判为偏离核心；记下标签、连续原文片段及具体缺陷。不用其他维度高分抵消否决。轻微可读性建议不必机械否决。

L1 Claim、L2 Mechanism、L3 Validation只是理解证明深度的可选层次，不是格式、句数、字符下限或数字要求。源事实只有职责声明时，检查是否如实保留边界、正文外说明缺口；不能要求补造机制或成果。简短而具体、没有量化成果的完整消息可以通过。

修订顺序：删除未证实推演 → 恢复同一项目中必要的材料机制/验证 → 重写全文衔接 → 重核主张、指标口径和贡献主体。既不以缩短，也不以改长判断成功；原事实、审批和发送门禁保持有效。

**Substance Check（事实实质）。** 暂去技术术语后，是否仍能理解真实用户的问题/任务、候选人的关键贡献及可验证产出？输入有实质内容却以并列职责或技术栈冒充深度，记`substance_gap`，实质证明损失时判为表达不通过；具体经历被压掉可同时记`depth_collapse`。检查设计理由是否有源，不要求每稿补一条决策动机、数字或项目。源材料缺细节时保留缺口，不能要求编造；语义充分的短稿及有用技术细节均可通过。

**Causal Grounding Check（因果接地）。** 核对问题、动作、成果及不同经历之间的关系本身，包含隐含因果、项目归属、动机与时序。两端各有来源不等于连接有来源；一般产品需求来源不能直接指认某具体项目立项，整体迭代结果不能直接归因于单一机制。未证实的连接记`unsupported_causal_link`，判为事实不通过；漏核的关系主张同样判事实不通过。全文连贯或端点均有依据不能抵消事实否决。

两项检查均引用准确连续原文及来源能/不能支持的范围。局部去掉无源关系、收窄或重组主线后重新核实；不让“启发、推动”等词继续携带同一未经确认的因果。只有发生实际表达或针对性问题时才追加相应质量否决，不机械全部否决。Overproduction、删除不补位、事实与准确全文人工审批门禁保持有效。

## B. Seven-dimension content review (works across professions)

| Dimension | Core question | Typical failure |
|---|---|---|
| D1 Positioning | Do the opening and self-introduction fit this conversation's goal, backed by the materials? | A label from an unrelated background that disqualifies the candidate up front |
| D2 Core need | Is the problem the employer most needs solved actually understood? | Keywords without the responsibility behind them |
| D3 Fact fit | Does the experience match the task in problem, action, constraint or result? | Same industry label, different mechanism |
| D4 Language fit | Is the real experience explained in terms the recipient understands? | Jargon (theirs or the candidate's internal terms), mechanical echo of the JD |
| D5 Result relevance | Do the chosen actions or outcomes prove the ability needed here? | Unrelated awards or metrics, a vague "launched", numbers whose meaning is unclear |
| D6 Depth and distinction | Does it show real personal contribution and distinctive value? | Only "participated" or "familiar with"; low-bar proof for an advanced ability |
| D7 Natural flow | Is it coherent, unstitched, and like a person wrote it? | Analyst voice, phrase blocks, abrupt turns, collage (see message-composition §2) |

Each dimension can be scored `0/1/2` (0 = fails, 1 = could be better, 2 = convincing). **The scores are a review tool, not an output template.** If D2 or D3 is 0, rewrite. A failed fact gate blocks the draft. Other problems get revised according to how serious they are. Without an actual independent review, never write "passed 7-dimension independent review".

**Self-check honesty.** A self-check that gives every dimension full marks across a whole batch is a warning sign, not a result. Name the weakest dimension for each draft.

**D3 Fact Fit 内的 Fact Selection Counterfactual。** Reviewer读取全部已提供候选人事实，独立暂时禁用当前主案例，比较实际替代的任务相关性、个人贡献、验证结果与表达成本，而非只核对作者选中的经历。若有综合证明力明显更强的案例，应建议换主线；没有则保留，不为多样性而换弱案例或要求并列多个项目。比较是定性判断，不设权重、固定行业映射或案例配额。

同时检查对该JD具有独特证明力的专业背景是否被错误删除；确实补足核心能力证明时，可作为简短支持事实保留，不需另写完整项目，也不能编造与主案例的因果。仅因没写凭证或另一段经历，不自动否决。

实质选材错误导致核心任务证明不足时，以`fact_selection`引用正文并指出有源替代及比较理由，判为偏离岗位核心；严重删掉独特背景、破坏核心能力证明时同样处理。较轻建议留在正文外notes，不让其他高分抵消实质问题。正文事实均真实时，不把选材不足冒充事实不通过；主张覆盖只核对正文，不代表遗漏了候选人的某段经历。保留现有事实、实质、因果、连贯性与审批门禁。

## C. Checklist

- [ ] Every substantive claim in the message links to a fact source; nothing missed and no scope inflated.
- [ ] One JD responsibility is clearly the centre; you can say why this experience and not another.
- [ ] Every sentence relates to the centre and follows from the one before.
- [ ] Important qualifiers survived shortening; no number turned into a different metric.
- [ ] Vocabulary and depth suit the recipient; no unexplained internal names or source-industry jargon.
- [ ] No third-party voice ("this role") or self-assessment ("a perfect match").
- [ ] Preferences applied only where in scope; a one-off edit is not generalised to other tasks.
- [ ] Nothing suggests the draft was sent, approved or successful.

## D. Batch checks (when drafting several messages)

Each message is written independently, but the batch is reviewed as a whole:

- **Repeated openings or clauses**: if a sentence or near-identical clause appears in several drafts (as a rough guide, three or more, or about a third of the batch), the drafts are drifting into a template. Rewrite the affected ones from their own JDs.
- **Same employer, several roles**: messages to the same company must differ in angle, not just in wording.
- **One experience everywhere**: if the same achievement leads most drafts, check whether it really answers each JD's core need, or is just the candidate's favourite.
- **Uniform scores**: see "Self-check honesty" above.

## E. Revision loop

- **Fact failure**: delete or narrow the unsupported claim, then re-check the whole message.
- **JD misunderstanding**: reread the original and choose a new centre. Don't polish over the error.
- **Wrong experience**: search the materials again. Don't cling to the original project.
- **Broken line**: change the overall structure and rewrite the whole message. Don't swap phrases.
- **Minor wording issues**: trim jargon, redundancy and forced transitions.

Re-check the full text after every rewrite. If the host updates the JD, candidate facts or preferences during review, regenerate from the new version. Never claim the current review used inputs it did not.
