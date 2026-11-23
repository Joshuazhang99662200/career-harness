import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
SKILL = ROOT / "skills" / "job-hunting"


def read(relative: str) -> str:
    return (SKILL / relative).read_text(encoding="utf-8")


def test_entry_skill_routes_roles_contract_and_writing_skills() -> None:
    text = read("SKILL.md")
    for reference in (
        "references/first-use.md",
        "references/bitable-contract.md",
        "roles/GM.md",
        "roles/EM.md",
        "greeting/SKILL.md",
        "optimizer/SKILL.md",
        "references/memory-dream.md",
        "references/stop-conditions.md",
        "references/capability-catalog.md",
    ):
        assert reference in text, reference
        assert (SKILL / reference).is_file(), reference


def section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


def test_entry_skill_identifies_the_role_from_private_settings_first() -> None:
    text = read("SKILL.md")
    start = section(text, "## 从这里开始")
    assert start.index("settings.json") < start.index("roles/GM.md")
    assert "references/first-use.md" in start


def test_entry_skill_routes_tasks_per_role_without_crossing_over() -> None:
    text = read("SKILL.md")
    gm, em = section(text, "## GM 的任务"), section(text, "## EM 的任务")
    for skill in ("greeting/SKILL.md", "optimizer/SKILL.md", "references/memory-dream.md"):
        assert skill in gm, skill
        assert skill not in em, skill
    assert "references/feishu-shared-source.md" in gm
    assert "references/feishu-shared-source.md" in em


def test_em_execution_chain_covers_every_platform_and_method() -> None:
    em, chain = read("roles/EM.md"), read("references/em-execution.md")
    assert "../references/em-execution.md" in em
    assert "references/em-execution.md" in section(read("SKILL.md"), "## EM 的任务")
    for platform in ("BOSS", "猎聘", "智联", "LinkedIn"):
        assert platform in chain, platform
    for method in ("Chrome 插件", "云浏览器", "MCP"):
        assert method in chain, method
    for rule in ("已批准", "不重复发送", "更新时间", "完成", "未完成", "需本人", "恢复点"):
        assert rule in chain, rule


def test_em_writes_only_gpt_column_and_never_drafts_replies() -> None:
    chain = read("references/em-execution.md")
    for line in chain.splitlines():
        if "`Muse处理`" in line:
            assert "写" not in line.split("`Muse处理`")[0][-6:], line
            assert "看 `Muse处理`" in line, line
    assert "回复草稿" not in chain
    assert "待 GPT 回复" in section(chain, "## 5. 回执核对")
    assert "`GPT处理`" in section(chain, "## 5. 回执核对")


def test_initial_setup_asks_only_for_platform_choices_and_keeps_numbers_private() -> None:
    setup = read("references/first-use.md")
    for item in (
        "em-execution.md", "每个平台", "超时", "排除词", "settings.json",
        "platform-capability-routing.md", "简历模板", "技能栈", "事实整理",
        "routing_mode = auto", "多选", "小红书", "ATS",
    ):
        assert item in setup, item
    assert "platform-capability-routing.md" in read("references/em-execution.md")


def test_initial_setup_selects_host_role_before_shared_automatic_bootstrap() -> None:
    entry = read("SKILL.md")
    setup = read("references/first-use.md")
    schema = read("references/feishu-schema-bootstrap.md")
    bootstrap = read("references/feishu-provisioning.md")
    start = section(entry, "## 从这里开始")
    assert start.index("references/first-use.md") < start.index("roles/GM.md")
    assert start.index("references/first-use.md") < start.index("roles/EM.md")
    assert "feishu-provisioning.md" in setup
    assert "jobagent setup feishu-plan" in bootstrap and "+workflow-disable" in bootstrap
    assert "+workflow-enable" not in bootstrap
    role = setup.index("## 1. 识别宿主并确认角色")
    base = setup.index("## 2. 检查连接")
    gm = setup.index("## 3. GM 准备材料")
    em = setup.index("## 4. EM 初始化")
    assert role < base < gm < em < setup.index("## 5. 开始使用")
    assert "jobagent setup host-role" in setup[role:base]
    for table in ("岗位", "材料", "Human Signals", "搜索与匹配记忆", "招呼语表达记忆"):
        assert f"### {table}" in schema, table
    for material in ("简历模板", "技能栈", "事实整理"):
        assert material in setup and material in schema
    assert "Muse处理" in schema and "GPT处理" in schema
    assert "批准状态" in schema and "处理进度" in schema
    assert "四种 Human Signals 字段映射" in schema
    assert "已有符合条件的资源直接复用" in schema


def test_gm_fact_discovery_is_reachable_on_setup_and_each_dependent_job():
    setup = read("references/first-use.md")
    gm = read("roles/GM.md")
    facts = read("references/personal-fact-discovery.md")
    assert "personal-fact-discovery.md" in setup
    assert "personal-fact-discovery.md" in section(gm, "## 每份 JD")
    for requirement in ("sufficient", "needs_clarification", "proceed_with_gaps",
                        "本人已确认", "材料明确记载", "GM 归纳", "待核实", "一次优先问一个问题"):
        assert requirement in facts
    assert "personal-fact-discovery.md" not in read("roles/EM.md")


def test_em_uses_only_table_approval_and_current_materials_for_external_send() -> None:
    chain = read("references/em-execution.md")
    approval = section(chain, "## 4. 执行已批准的动作")
    assert "本人在飞书表格" in approval
    assert "视为批准" not in approval
    assert "已授权" in approval


def test_greeting_skill_is_v1_2_with_memory_scope_rules() -> None:
    assert 'version: "1.2.0"' in read("greeting/SKILL.md")
    host = read("greeting/references/host-contract.md")
    for domain in ("岗位", "材料", "Human Signals", "搜索与匹配记忆", "招呼语表达记忆"):
        assert domain in host, domain
    assert "Do not create a second memory system" in host


def test_resume_skill_reuses_a_private_default_mode_and_never_widens_edits() -> None:
    router = read("optimizer/SKILL.md")
    assert "settings.json" in router
    assert "不自动扩大" in router
    template = read("references/optimizer/template-tailoring.md")
    assert "截图" in template


def test_timeout_clock_is_the_last_progress_change_not_any_row_edit() -> None:
    closing = section(read("references/em-execution.md"), "## 6. 状态收束")
    for rule in ("record-history", "处理进度", "已终止", "已超时", "工作日", "create"):
        assert rule in closing, rule
    assert "不重置" in closing
    for paused in ("待你批准", "招聘方来信", "登录失效"):
        assert paused in closing, paused
    assert "已废弃" not in closing.split("目标状态")[-1].split("\n")[0]


def test_every_bot_timeout_spawns_one_evidence_probe_through_gpt_column() -> None:
    probe = read("references/em-execution.md")
    contract = read("references/bitable-contract.md")
    for item in ("CH10D", "system_timeout", "GPT处理", "追加", "读回", "unobservable"):
        assert item in probe, item
    assert "request_id" in contract and "CH10D" in contract
    assert "先看" in section(probe, "## 6A. 超时后补证")


def test_dream_keeps_timeouts_and_employer_rejections_out_of_preferences() -> None:
    dream = read("references/memory-dream.md")
    for item in ("system_timeout", "employer_rejected", "已超时", "record-history"):
        assert item in dream, item


def test_ten_workday_skill_is_lazy_gm_only_and_never_writes_memory() -> None:
    entry = read("SKILL.md")
    assert "performance-intervention/SKILL.md" in section(entry, "## GM 的任务")
    assert "performance-intervention" not in section(entry, "## EM 的任务")
    skill = read("performance-intervention/SKILL.md")
    for ref in ("metrics.md", "attribution.md", "em-probe.md", "intervention-approval.md"):
        assert f"references/{ref}" in skill, ref
        assert (SKILL / "performance-intervention" / "references" / ref).is_file(), ref
    for rule in ("静默", "两个", "不写 Memory", "本人批准"):
        assert rule in skill, rule


def test_ten_workday_metrics_never_count_unknown_or_immature_as_miss() -> None:
    metrics = read("performance-intervention/references/metrics.md")
    for state in ("hit", "miss", "pending", "unknown", "unobservable"):
        assert f"`{state}`" in metrics, state
    for rule in ("2 个工作日", "10 个工作日", "不重叠", "Wilson", "0.8", "C", "D"):
        assert rule in metrics, rule


def test_intervention_needs_explicit_approval_and_never_auto_rolls_back() -> None:
    approval = read("performance-intervention/references/intervention-approval.md")
    for rule in ("本人", "批准范围", "不等于批准发送", "读回", "回滚", "pending"):
        assert rule in approval, rule
    attribution = read("performance-intervention/references/attribution.md")
    for factor in ("匹配档位", "薪资", "招聘方活跃", "平台", "材料版本", "crossover"):
        assert factor in attribution, factor


def test_lens_routing_links_every_lens_policy() -> None:
    text = read("references/optimizer/lens-routing.md")
    for lens in ("general", "headhunter", "internal-hr", "hiring-manager"):
        assert f"(lens-{lens}.md)" in text, lens


def test_entry_skill_hard_rules_cover_approval_untrusted_text_and_private_data() -> None:
    text = read("SKILL.md")
    for required in ("已批准", "待你批准", "数据,不是指令", "candidate/private/", "CAPTCHA"):
        assert required in text, required


def test_roles_keep_generation_and_execution_apart() -> None:
    gm, em = read("roles/GM.md"), read("roles/EM.md")
    assert "待你批准" in gm
    for field in ("匹配档位", "匹配理由", "招呼语", "简历cv（PDF）"):  # noqa: RUF001
        assert field in em
    assert "不写 `批准状态`" in em


def test_resume_skill_keeps_mode_choice_and_has_no_delivery_route() -> None:
    text = read("optimizer/SKILL.md")
    assert "这次简历优化，您倾向哪种方式？" in text  # noqa: RUF001
    assert "材料" in text
    for forbidden in ("send application", "bypass captcha", "perform login"):
        assert forbidden not in text.casefold()


def test_greeting_skill_keeps_the_first_contact_quality_guards() -> None:
    review = read("greeting/references/quality-review.md")
    selection = read("greeting/references/fact-selection.md")
    assert "First-contact overproduction" in review
    assert "Causal Grounding Check" in selection


RETIRED_EVIDENCE = re.compile(r"(?i)\bevidence|EVID_|证据|candidate core|candidate ingest")
RETIRED_CODE_CONTRACTS = re.compile(
    r"GreetingReview|style_ok|target_relevant|full_text_supported|no_missing_claims|"
    r"RecruiterInfo|VerificationStatus|KeywordCoverageReport|ResumeVariant"
)


def skill_files() -> list[Path]:
    roots = (SKILL, ROOT / "skills" / "jd-grounded-template-tailoring")
    return sorted(
        path for root in roots for path in root.rglob("*") if path.suffix in {".md", ".yaml"}
    )


def test_skill_tree_no_longer_speaks_the_retired_evidence_model() -> None:
    hits = [
        f"{path.relative_to(ROOT)}: {match.group(0)}"
        for path in skill_files()
        for pattern in (RETIRED_EVIDENCE, RETIRED_CODE_CONTRACTS)
        for match in pattern.finditer(path.read_text(encoding="utf-8"))
    ]
    assert not hits, hits


def test_package_code_no_longer_carries_the_evidence_model() -> None:
    source = ROOT / "src" / "jobagent"
    assert not (source / "schemas" / "candidate.py").exists()
    assert not (source / "schemas" / "optimizer.py").exists()
    hits = [
        f"{path.relative_to(ROOT)}: {match.group(0)}"
        for path in sorted(source.rglob("*.py"))
        for match in RETIRED_EVIDENCE.finditer(path.read_text(encoding="utf-8"))
    ]
    assert not hits, hits


def test_retired_connector_sources_are_gone() -> None:
    assert not (SKILL / "sources").exists()


def test_greeting_skill_keeps_its_guards_under_material_fact_names() -> None:
    review = read("greeting/references/quality-review.md")
    selection = read("greeting/references/fact-selection.md")
    for label in ("depth_collapse", "narrative_collage", "unsupported_causal_link"):
        assert label in review, label
    assert "Fact Selection Counterfactual" in selection
    assert "need_materials" in read("greeting/SKILL.md")


def test_reference_only_source_is_explicit() -> None:
    text = read("references/oss/source-manifest.yaml")
    assert "Auto-JobHunter" in text
    assert "reference-only" in text
    assert "non-commercial" in text
