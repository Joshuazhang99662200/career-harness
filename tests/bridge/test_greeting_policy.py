"""The bundled jd-greeting method is part of the greeting policy, after the harness rules."""

from jobagent.bridge.greeting_policy import DEFAULT_METHOD, PRECEDENCE, greeting_policy
from jobagent.skill_resources import default_skill_root, read_reference


def test_policy_puts_harness_rules_first_then_the_bundled_method():
    policy = greeting_policy()
    harness = read_reference("references/greeting-ai.md")
    assert policy.startswith(harness)
    assert policy.index(PRECEDENCE) > len(harness)
    for path in DEFAULT_METHOD:
        assert read_reference(path) in policy
    # Synthetic examples stay out of the prompt so they cannot act as a phrase bank.
    assert "synthetic-examples" not in "".join(DEFAULT_METHOD)
    assert read_reference("greeting/references/synthetic-examples.md") not in policy


def test_the_bundled_skill_keeps_its_license_and_version():
    root = default_skill_root()
    skill = (root / "greeting/SKILL.md").read_text(encoding="utf-8")
    assert "name: jd-greeting" in skill and 'version: "1.1.0"' in skill
    license_text = (root.parents[1] / "LICENSES/JD-Greeting-MIT.txt").read_text(encoding="utf-8")
    assert "MIT License" in license_text
