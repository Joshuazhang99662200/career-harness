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
    for forbidden in ("send application", "bypass captcha", "perform login", "canonical Evidence"):
        assert forbidden not in text.casefold()


def test_greeting_skill_keeps_the_first_contact_quality_guards() -> None:
    review = read("greeting/references/quality-review.md")
    reasoning = read("greeting/references/evidence-reasoning.md")
    assert "First-contact overproduction" in review
    assert "evidence_collapse" in review
    assert "Evidence Selection Counterfactual" in reasoning
    assert "Causal Grounding Check" in reasoning


def test_reference_only_source_is_explicit() -> None:
    text = read("references/oss/source-manifest.yaml")
    assert "Auto-JobHunter" in text
    assert "reference-only" in text
    assert "non-commercial" in text
