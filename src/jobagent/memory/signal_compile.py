"""Validate a host attribution and publish bounded memory. No model call lives here."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from jobagent.digest import canonical_digest, text_digest
from jobagent.errors import ContractValidationError, InvalidProviderOutputError
from jobagent.schemas.memory_signal import (
    AttributionRequest,
    CompileResult,
    HumanFeedbackSignal,
    JobSignalContext,
    MemoryDraft,
    PreferenceLabel,
    PublishedMemory,
    SignalAttribution,
)

_ALLOWED: dict[PreferenceLabel, frozenset[str]] = {
    "Matching Preference / Calibration": frozenset({"matching", "search"}),
    "Greeting Preference": frozenset({"greeting"}),
    "Workflow / Operational Preference": frozenset({"workflow"}),
}
_REQUIRED: dict[PreferenceLabel, str] = {
    "Matching Preference / Calibration": "matching",
    "Greeting Preference": "greeting",
    "Workflow / Operational Preference": "workflow",
}


class SignalAttributor(Protocol):
    def attribute(self, request: AttributionRequest) -> SignalAttribution: ...


def build_request(signal: HumanFeedbackSignal, context: JobSignalContext) -> AttributionRequest:
    if context.record_id != signal.record_id:
        raise ContractValidationError("Job context is for a different Bitable record.")
    greeting_digest = (
        None if context.generated_greeting is None else text_digest(context.generated_greeting)
    )
    jd_digest = text_digest(context.jd_text)
    payload = {
        "signal_id": signal.signal_id,
        "event_id": signal.event_id,
        "record_id": signal.record_id,
        "field_id": signal.field_id,
        "preference": signal.preference,
        "before_value": signal.before_value,
        "after_value": signal.after_value,
        "candidate_id": context.candidate_id,
        "job_id": context.job_id,
        "jd_digest": jd_digest,
        "original_greeting_digest": greeting_digest,
        "role_direction": context.role_direction,
    }
    return AttributionRequest(
        signal=signal,
        candidate_id=context.candidate_id,
        job_id=context.job_id,
        jd_text=context.jd_text,
        jd_digest=jd_digest,
        generated_greeting=context.generated_greeting,
        original_greeting_digest=greeting_digest,
        title=context.title,
        company=context.company,
        role_direction=context.role_direction,
        input_digest=canonical_digest(payload),
    )


def _search_fields(draft: MemoryDraft) -> bool:
    return bool(draft.keywords or draft.role_directions or draft.exclusions)


def accept_attribution(
    request: AttributionRequest, attribution: SignalAttribution
) -> list[PublishedMemory]:
    signal = request.signal
    attribution = SignalAttribution.model_validate(attribution.model_dump())
    if (
        attribution.signal_id != signal.signal_id
        or attribution.event_id != signal.event_id
        or attribution.record_id != signal.record_id
        or attribution.jd_digest != request.jd_digest
        or attribution.original_greeting_digest != request.original_greeting_digest
        or attribution.input_digest != request.input_digest
    ):
        raise InvalidProviderOutputError(
            "Signal attribution does not match the JD and original greeting it was given."
        )
    allowed = _ALLOWED[signal.preference]
    kinds = [draft.kind for draft in attribution.drafts]
    if len(kinds) != len(set(kinds)) or any(kind not in allowed for kind in kinds):
        raise InvalidProviderOutputError(
            "Signal attribution crosses the preference class of the edited field."
        )
    if _REQUIRED[signal.preference] not in kinds:
        raise InvalidProviderOutputError(
            "Signal attribution is missing the memory kind for this field."
        )
    published: list[PublishedMemory] = []
    for draft in attribution.drafts:
        if draft.kind == "search":
            if not _search_fields(draft):
                raise InvalidProviderOutputError(
                    "Search memory must name a keyword, role direction or exclusion."
                )
        elif _search_fields(draft) or not draft.notes:
            raise InvalidProviderOutputError(
                "Only search memory may change search parameters, and it must say why."
            )
        identity = canonical_digest(
            {
                "signal_id": signal.signal_id,
                "kind": draft.kind,
                "reason": draft.reason,
                "keywords": draft.keywords,
                "role_directions": draft.role_directions,
                "exclusions": draft.exclusions,
                "notes": draft.notes,
            }
        )
        published.append(
            PublishedMemory(
                memory_id="MEM_" + identity[7:27].upper(),
                kind=draft.kind,
                preference=signal.preference,
                candidate_id=request.candidate_id,
                source_event_id=signal.event_id,
                source_signal_id=signal.signal_id,
                record_id=signal.record_id,
                job_id=request.job_id,
                reason=draft.reason,
                keywords=list(draft.keywords),
                role_directions=list(draft.role_directions),
                exclusions=list(draft.exclusions),
                notes=list(draft.notes),
                jd_digest=request.jd_digest,
            )
        )
    return published


class FileAttributor:
    """Attributions already produced by the host model. This class does not call one."""

    def __init__(self, items: Sequence[SignalAttribution]) -> None:
        self.items: dict[str, SignalAttribution] = {}
        for item in items:
            item = SignalAttribution.model_validate(item.model_dump())
            current = self.items.get(item.signal_id)
            if current is not None and current != item:
                raise ContractValidationError("The same signal has two different attributions.")
            self.items[item.signal_id] = item

    def attribute(self, request: AttributionRequest) -> SignalAttribution:
        found = self.items.get(request.signal.signal_id)
        if found is None:
            raise ContractValidationError("No attribution was provided for this human signal.")
        return found


class SignalCompiler:
    def __init__(
        self,
        contexts: Mapping[str, JobSignalContext],
        attributor: SignalAttributor,
    ) -> None:
        self.contexts = {
            key: JobSignalContext.model_validate(value.model_dump())
            for key, value in contexts.items()
        }
        self.attributor = attributor
        self._learned: dict[str, list[PublishedMemory]] = {}
        self.calls = 0

    def remember(self, memories: Sequence[PublishedMemory]) -> None:
        for memory in memories:
            memory = PublishedMemory.model_validate(memory.model_dump())
            bucket = self._learned.setdefault(memory.source_signal_id, [])
            if memory not in bucket:
                bucket.append(memory)

    def export(self) -> list[PublishedMemory]:
        exported: list[PublishedMemory] = []
        for bucket in self._learned.values():
            exported.extend(bucket)
        return exported

    def compile(self, signals: Sequence[HumanFeedbackSignal]) -> CompileResult:
        memories: list[PublishedMemory] = []
        duplicates: list[str] = []
        missing: list[str] = []
        for signal in signals:
            signal = HumanFeedbackSignal.model_validate(signal.model_dump())
            cached = self._learned.get(signal.signal_id)
            if cached is not None:
                memories.extend(cached)
                duplicates.append(signal.signal_id)
                continue
            context = self.contexts.get(signal.record_id)
            if context is None:
                missing.append(signal.signal_id)
                continue
            request = build_request(signal, context)
            self.calls += 1
            memories_for_signal = accept_attribution(request, self.attributor.attribute(request))
            self._learned[signal.signal_id] = memories_for_signal
            memories.extend(memories_for_signal)
        return CompileResult(
            memories=memories,
            duplicate_signal_ids=duplicates,
            unassociated_signal_ids=missing,
        )
