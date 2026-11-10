"""The writing policy that greeting drafting and its independent review both follow.

CareerHarness rules come first. The bundled jd-greeting skill (v1.1.0, MIT) is the
default method for reading a JD, choosing evidence, composing and reviewing. Its
synthetic examples are left out of the prompt so they cannot act as a phrase bank.
"""

from jobagent.skill_resources import read_reference

HARNESS_POLICY = "references/greeting-ai.md"
DEFAULT_METHOD = (
    "greeting/SKILL.md",
    "greeting/references/host-contract.md",
    "greeting/references/jd-understanding.md",
    "greeting/references/evidence-reasoning.md",
    "greeting/references/message-composition.md",
    "greeting/references/quality-review.md",
)
POLICY_REFERENCES = (HARNESS_POLICY, *DEFAULT_METHOD)

PRECEDENCE = (
    "# Default greeting method (bundled jd-greeting v1.1.0)\n\n"
    "Follow this method for understanding the JD, choosing evidence, composing and "
    "reviewing. Where it differs from the CareerHarness rules above, those rules win: "
    "the output is GreetingDraft or GreetingReview, not the JSON shape or statuses "
    "suggested below; facts come only from the request's confirmed evidence; "
    "preference_memory and rules-file values are the host's preferences; nothing is "
    "ever sent or approved. Where the method would return need_jd, need_evidence or "
    "low_fit, do not write a draft that looks qualified: keep it narrow and say why, so "
    "the independent review rejects it."
)


def greeting_policy() -> str:
    """The exact policy text; its digest pins drafts and reviews to one version."""
    harness = read_reference(HARNESS_POLICY)
    method = "\n\n".join(read_reference(path) for path in DEFAULT_METHOD)
    return f"{harness}\n\n{PRECEDENCE}\n\n{method}"
