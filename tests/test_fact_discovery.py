import json

import pytest
from typer.testing import CliRunner

from jobagent.cli.app import app
from jobagent.setup.facts import FactDiscoveryRequest, plan_fact_discovery


def source(ref="resume", kind="pdf", status="read", confirmed_by_user=False):
    return dict(ref=ref, kind=kind, status=status, confirmed_by_user=confirmed_by_user)


def claim(text="Owned the release", status="documented", refs=("resume",), question=None,
          skipped=False):
    return dict(claim=text, status=status, source_refs=refs, question=question, skipped=skipped)


def plan(**request):
    return plan_fact_discovery(FactDiscoveryRequest.model_validate(
        {"materials_complete": True, **request},
    ))


def test_three_assets_are_checked_in_the_existing_record():
    result = plan(records=[dict(record_id="master", has_facts=True, has_skills=True)],
                  sources=[source(), source("facts", "facts"), source("skills", "skills")],
                  assessed=True, claims=[claim()])
    assert (result.material_record_id, result.record_action) == ("master", "reuse")
    assert (result.facts_action, result.skills_action) == ("review_update", "review_update")
    assert result.status == "sufficient"
    assert result.question is None


@pytest.mark.parametrize("kind", ["pdf", "word", "project", "text"])
def test_usable_original_material_can_draft_both_assets(kind):
    result = plan(sources=[source("original", kind)])
    assert result.status == "assess_coverage"
    assert result.record_action == "create_if_absent"
    assert (result.facts_action, result.skills_action) == ("draft", "draft")


@pytest.mark.parametrize(("record", "kind", "actions"), [
    (dict(has_facts=True), "facts", ("review_update", "draft")),
    (dict(has_skills=True), "skills", ("draft", "review_update")),
])
def test_one_asset_can_be_used_to_build_the_other_in_place(record, kind, actions):
    result = plan(records=[dict(record, record_id="master")], sources=[source(kind, kind)])
    assert result.record_action == "reuse"
    assert (result.facts_action, result.skills_action) == actions


def test_missing_all_material_starts_with_an_interview_and_waits_to_create_the_record():
    result = plan()
    assert result.status == "needs_clarification"
    assert result.question
    assert result.record_action == "wait"
    assert (result.facts_action, result.skills_action) == ("wait", "wait")


def test_existing_record_is_not_overwritten_when_an_attachment_cannot_be_read():
    result = plan(records=[dict(record_id="master", has_facts=True)],
                  sources=[source(), source("existing-facts", "facts", "unavailable")])
    assert result.record_action == "reuse"
    assert result.facts_action == "preserve"
    assert result.skills_action == "draft"


def test_unread_material_and_incomplete_table_are_not_treated_as_absence():
    assert plan(materials_complete=False).status == "inspect_materials"
    unresolved = plan(records=[dict(record_id="master", has_facts=True)])
    assert unresolved.status == "read_sources"
    assert plan(sources=[source(status="pending")]).status == "read_sources"


def test_target_relevant_gap_drives_one_question_then_an_answer_is_reassessed():
    result = plan(sources=[source()], assessed=True, claims=[
        claim(), claim("Designed rollout boundaries", "unverified", (),
                       "Who set the rollout boundaries?"),
        claim("Vendor count", "conflicting", (), "How many vendors were involved?"),
    ])
    assert result.status == "needs_clarification"
    assert result.question == "Who set the rollout boundaries?"
    final = plan(sources=[source(), source("answer", "interview", confirmed_by_user=True)],
                 assessed=True, claims=[
        claim(), claim("Designed rollout boundaries", "confirmed", ("answer",)),
    ])
    assert final.status == "sufficient"
    assert final.question is None


def test_only_a_source_with_explicit_confirmation_can_validate_a_confirmed_claim():
    result = plan(sources=[source()], assessed=True,
                  claims=[claim(status="confirmed")])
    assert result.status == "needs_clarification"
    assert result.usable_claims == []
    assert "Owned the release" in result.question


def test_inference_and_inaccessible_sources_cannot_support_a_claim():
    result = plan(sources=[source(), source("other", "project", "unavailable")], assessed=True,
                  claims=[claim("Led a team", "inferred", ("resume",), skipped=True),
                          claim("Raised revenue", "confirmed", ("other",), skipped=True),
                          claim("Shipped a product", "documented", ("missing",), skipped=True)])
    assert result.status == "proceed_with_gaps"
    assert result.usable_claims == []
    assert result.gaps == ["Led a team", "Raised revenue", "Shipped a product"]


def test_skipping_the_interview_does_not_create_empty_assets():
    result = plan(skip_interview=True)
    assert result.status == "proceed_with_gaps"
    assert result.record_action == "wait"
    assert result.usable_claims == []


def test_idempotent_restart_never_creates_another_master_and_reports_ambiguous_rows():
    initial = plan(sources=[source()])
    material = dict(record_id="master", has_facts=True, has_skills=True)
    resume = plan(records=[material], bound_record_id="master",
                  sources=[source("facts", "facts"), source("skills", "skills")])
    assert initial.record_action == "create_if_absent"
    assert resume.record_action == "reuse"
    assert resume.material_record_id == "master"
    ambiguous = plan(records=[material, dict(record_id="other")])
    assert ambiguous.status == "resolve_material_record"
    assert ambiguous.record_action == "wait"


def test_unknown_record_creation_result_never_repeats_the_create():
    result = plan(sources=[source()], creation_pending=True)
    assert result.status == "resolve_material_record"
    assert result.record_action == "wait"
    recovered = plan(sources=[source()], creation_pending=True,
                     records=[dict(record_id="master")])
    assert recovered.record_action == "reuse"


def test_cli_plans_no_material_interview_without_writing_files(tmp_path):
    request = tmp_path / "facts.json"
    content = '{"materials_complete":true}'
    request.write_text(content, encoding="utf-8")
    result = CliRunner().invoke(app, ["setup", "personal-facts", "--request", str(request)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "needs_clarification"
    assert list(tmp_path.iterdir()) == [request]
    assert request.read_text(encoding="utf-8") == content
