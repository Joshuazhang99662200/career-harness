"""Plan the GM's material work and coverage questions from private source observations."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from jobagent.setup.bootstrap import PrivateInput

AssetKind = Literal["facts", "skills"]
AssetAction = Literal["wait", "draft", "review_update", "preserve"]
PlanStatus = Literal[
    "inspect_materials", "resolve_material_record", "read_sources", "assess_coverage",
    "needs_clarification", "sufficient", "proceed_with_gaps",
]
FIRST_INTERVIEW_QUESTION = (
    "请从最近一段与目标岗位相关的工作经历说起。那段经历里，您主要负责什么？"  # noqa: RUF001
)


class MaterialRecord(PrivateInput):
    record_id: str = Field(min_length=1)
    has_facts: bool = False
    has_skills: bool = False


class MaterialSource(PrivateInput):
    ref: str = Field(min_length=1)
    kind: Literal["pdf", "word", "project", "text", "interview", "facts", "skills"]
    status: Literal["pending", "read", "unavailable"] = "pending"
    confirmed_by_user: bool = False


class CoverageClaim(PrivateInput):
    claim: str = Field(min_length=1)
    status: Literal["confirmed", "documented", "inferred", "unverified", "conflicting"]
    source_refs: list[str] = Field(default_factory=list)
    question: str | None = Field(default=None, min_length=1)
    skipped: bool = False


class FactDiscoveryRequest(PrivateInput):
    materials_complete: bool = False
    records: list[MaterialRecord] = Field(default_factory=list)
    bound_record_id: str | None = None
    creation_pending: bool = False
    sources: list[MaterialSource] = Field(default_factory=list)
    assessed: bool = False
    claims: list[CoverageClaim] = Field(default_factory=list)
    skip_interview: bool = False

    @model_validator(mode="after")
    def unique_observations(self) -> "FactDiscoveryRequest":
        if len({record.record_id for record in self.records}) != len(self.records):
            raise ValueError("Material record IDs must be unique.")
        if len({source.ref for source in self.sources}) != len(self.sources):
            raise ValueError("Material source references must be unique.")
        return self


class FactDiscoveryPlan(BaseModel):
    status: PlanStatus
    material_record_id: str | None = None
    record_action: Literal["wait", "reuse", "create_if_absent"] = "wait"
    facts_action: AssetAction = "wait"
    skills_action: AssetAction = "wait"
    question: str | None = None
    usable_claims: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


def plan_fact_discovery(request: FactDiscoveryRequest) -> FactDiscoveryPlan:
    if not request.materials_complete:
        return FactDiscoveryPlan(status="inspect_materials")
    records = {record.record_id: record for record in request.records}
    if request.bound_record_id:
        master = records.get(request.bound_record_id)
        if master is None:
            return FactDiscoveryPlan(status="resolve_material_record")
    elif len(records) > 1:
        return FactDiscoveryPlan(status="resolve_material_record")
    else:
        master = next(iter(records.values()), None)
    if request.creation_pending and master is None:
        return FactDiscoveryPlan(status="resolve_material_record")
    sources = request.sources
    kinds = {source.kind for source in sources}
    if (any(source.status == "pending" for source in sources)
            or (master and master.has_facts and "facts" not in kinds)
            or (master and master.has_skills and "skills" not in kinds)):
        return FactDiscoveryPlan(status="read_sources", material_record_id=(
            master.record_id if master else None
        ))

    readable = {source.ref for source in sources if source.status == "read"}
    result = FactDiscoveryPlan(status="assess_coverage")
    if master:
        result.material_record_id = master.record_id
        result.record_action = "reuse"
    elif readable:
        result.record_action = "create_if_absent"
    result.facts_action = _asset_action("facts", bool(master and master.has_facts), sources)
    result.skills_action = _asset_action("skills", bool(master and master.has_skills), sources)

    if not readable and not request.claims:
        result.status = "proceed_with_gaps" if request.skip_interview else "needs_clarification"
        if not request.skip_interview:
            result.question = FIRST_INTERVIEW_QUESTION
    elif request.assessed:
        _apply_coverage(result, request, readable)
    return result


def _asset_action(kind: AssetKind, exists: bool, sources: list[MaterialSource]) -> AssetAction:
    if exists:
        if any(source.kind == kind and source.status == "read" for source in sources):
            return "review_update"
        return "preserve"
    return "draft" if any(source.status == "read" for source in sources) else "wait"


def _apply_coverage(
    result: FactDiscoveryPlan, request: FactDiscoveryRequest, readable: set[str],
) -> None:
    explicitly_confirmed = {
        source.ref for source in request.sources
        if source.confirmed_by_user and source.status == "read"
    }
    unresolved: list[CoverageClaim] = []
    for candidate in request.claims:
        refs = set(candidate.source_refs)
        supported = candidate.status == "documented" or (
            candidate.status == "confirmed" and bool(refs & explicitly_confirmed)
        )
        if supported and refs and refs <= readable:
            result.usable_claims.append(candidate.claim)
        else:
            unresolved.append(candidate)
    result.gaps = [claim.claim for claim in unresolved]
    if not unresolved:
        result.status = "sufficient"
        return
    pending = next((claim for claim in unresolved if not claim.skipped), None)
    if request.skip_interview or pending is None:
        result.status = "proceed_with_gaps"
        return
    result.status = "needs_clarification"
    result.question = pending.question or (
        f"关于「{pending.claim}」，您本人实际负责哪一部分？"  # noqa: RUF001
    )
