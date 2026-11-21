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


def test_initial_setup_asks_each_platform_and_keeps_numbers_private() -> None:
    setup = read("references/first-use.md")
    for item in (
        "em-execution.md", "每个平台", "超时", "排除词", "settings.json",
        "feishu-schema-bootstrap.md", "简历模板", "技能栈", "事实整理",
    ):
        assert item in setup, item


def test_initial_setup_requires_user_created_base_before_business_skills() -> None:
    entry = read("SKILL.md")
    setup = read("references/first-use.md")
    schema = read("references/feishu-schema-bootstrap.md")
    assert "references/feishu-schema-bootstrap.md" in entry
    assert "先在飞书建立 Base" in setup
    assert setup.index("## 1. 请用户先在飞书建立 Base") < setup.index(
        "## 6. 业务 Skill 解锁与首次运行"
    )
    for table in ("岗位", "材料", "Human Signals", "搜索与匹配记忆", "招呼语表达记忆"):
        assert f"### {table}" in schema, table
    for material in ("简历模板", "技能栈", "事实整理"):
        assert material in setup and material in schema
    assert "Muse处理" in schema and "GPT处理" in schema
    assert "批准状态" in schema and "处理进度" in schema
    assert "四个 Human Signals 自动化 Workflow" in schema
    assert "不重复要求创建" in setup or "不要求重新建立" in schema


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
