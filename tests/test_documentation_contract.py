import re
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).parents[1]


def test_oss_review_records_all_sources() -> None:
    text = (ROOT / "docs/oss-review.md").read_text(encoding="utf-8")
    for project in ("AgentMesh-JobAgent", "open-boss", "Auto-JobHunter"):
        assert project in text


def test_release_contract_files_exist() -> None:
    """The foundation design requires these before a public release."""
    for name in (
        "README.md",
        "LICENSE",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "PRIVACY.md",
        "AGENTS.md",
        ".env.example",
    ):
        assert (ROOT / name).is_file(), name


def test_env_example_carries_no_values() -> None:
    """The template must never ship a real key."""
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            assert line.endswith("="), line


def test_readme_links_the_release_contract_documents() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for target in ("CONTRIBUTING.md", "SECURITY.md", "PRIVACY.md", "AGENTS.md"):
        assert target in text


def test_agent_guide_routes_the_bitable_roles() -> None:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8-sig")
    for required in (
        "skills/job-hunting/roles/GM.md",
        "skills/job-hunting/roles/EM.md",
        "skills/job-hunting/references/bitable-contract.md",
        "待你批准",
    ):
        assert required in text, required
    for retired in ("写入私有 SQLite", "CandidateEvidenceService.confirm", "canonical Evidence"):
        assert retired not in text, retired


@pytest.mark.parametrize("path", [
    "AGENTS.md",
    "CONTRIBUTING.md",
    "docs/README.md",
    "hosts/personal-ai/tasks.md",
    "skills/job-hunting/SKILL.md",
    "skills/job-hunting/references/first-use.md",
    "skills/job-hunting/roles/GM.md",
    "skills/job-hunting/roles/EM.md",
])
def test_active_entry_points_link_to_the_owner_only_trace_contract(path: str) -> None:
    source = (ROOT / path).read_text(encoding="utf-8-sig")
    assert "human-signal-capture.md" in source


def test_active_documentation_links_resolve() -> None:
    pending = [ROOT / name for name in (
        "README.md", "AGENTS.md", "CONTRIBUTING.md", "docs/README.md",
        "hosts/personal-ai/README.md", "hosts/personal-ai/tasks.md",
        "skills/job-hunting/SKILL.md",
    )]
    visited = set()
    while pending:
        source = pending.pop()
        if source in visited:
            continue
        assert source.is_file(), source.relative_to(ROOT)
        visited.add(source)
        text = source.read_text(encoding="utf-8-sig")
        for link in re.findall(r"\]\(([^)\s]+)\)", text):
            if link.startswith("#") or re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", link):
                continue
            path = unquote(link.split("#", 1)[0])
            target = (source.parent / path).resolve()
            assert target.is_relative_to(ROOT), (source.relative_to(ROOT), link)
            assert target.exists(), (source.relative_to(ROOT), link)
            historical = any(part in {"superpowers", "reviews"} for part in target.parts)
            if target.suffix == ".md" and not historical:
                pending.append(target)


@pytest.mark.parametrize("name", ["README.md", "hosts/personal-ai/README.md"])
def test_current_onboarding_points_to_the_current_repository(name: str) -> None:
    text = (ROOT / name).read_text(encoding="utf-8")
    current = "Joshuazhang99662200/career-harness"
    previous = "Joshuazhang99662200/" + "full-stack-ai-jobagent"
    assert current in text, name
    assert previous not in text, name
    if "git clone" in text:
        assert f"git clone https://github.com/{current}.git" in text
        assert "cd career-harness" in text
