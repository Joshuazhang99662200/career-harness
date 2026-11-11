"""Effect claims about memory need closed windows, enough samples and honest intervals."""

from datetime import UTC, datetime, timedelta

import pytest

from jobagent.memory.effect import (
    compare_rates,
    newcombe_difference,
    reply_outcomes,
    wilson_interval,
)
from jobagent.schemas.conversation import (
    Conversation,
    ConversationEvent,
    EventKind,
    InboundMessage,
    MessageLevel,
)
from jobagent.schemas.memory import SentOutreach

NOW = datetime(2026, 11, 20, tzinfo=UTC)
WINDOW = timedelta(days=7)


def sent(job_id: str, at: datetime, *, version: str | None = "PMEM_V1") -> SentOutreach:
    return SentOutreach(
        batch_id="OBATCH_SIM", number=1, job_id=job_id, platform="boss", sent_at=at,
        memory_version=version, preference_rule_ids=["RULE_A"] if version else [],
    )


def conversation(job_id: str, *replies: datetime) -> tuple[Conversation, list[ConversationEvent]]:
    conv = Conversation(
        conversation_id=f"CONV_{job_id.removeprefix('JOB_')}", platform="boss", job_id=job_id,
        company="Synthetic", title="Role", origin="outreach", opened_at=NOW - timedelta(days=30),
    )
    events = [
        ConversationEvent(
            event_id=f"CEVT_{job_id.removeprefix('JOB_')}_{seq}",
            conversation_id=conv.conversation_id,
            seq=seq, kind=EventKind.INBOUND, recorded_at=at,
            inbound=InboundMessage(text="您好", level=MessageLevel.L1, received_at=at),
        )
        for seq, at in enumerate(replies, start=1)
    ]
    return conv, events


def test_replies_count_only_after_the_send_and_inside_a_closed_window():
    early = NOW - timedelta(days=20)
    items = [
        sent("JOB_A", early),                       # replied on day 2
        sent("JOB_B", early),                       # replied before the send: not a reply
        sent("JOB_C", early),                       # replied after the window: no reply
        sent("JOB_D", NOW - timedelta(days=2)),     # window still open: pending
    ]
    threads = [
        conversation("JOB_A", early + timedelta(days=2)),
        conversation("JOB_B", early - timedelta(hours=1)),
        conversation("JOB_C", early + timedelta(days=9)),
        conversation("JOB_D", NOW - timedelta(days=1)),
    ]
    outcomes = reply_outcomes(items, threads, now=NOW, window=WINDOW)
    assert [o.status for o in outcomes] == ["replied", "no_reply", "no_reply", "pending"]


def test_wilson_and_newcombe_intervals_match_known_values():
    low, high = wilson_interval(20, 100)
    assert (round(low, 4), round(high, 4)) == (0.1334, 0.2888)
    low, high = newcombe_difference((30, 100), (20, 100))
    assert low < 0.1 < high and round(low, 3) == -0.02


@pytest.mark.parametrize(
    ("treated", "baseline", "verdict"),
    [
        ((5, 10), (1, 10), "insufficient_sample"),
        ((60, 200), (40, 200), "higher"),
        ((40, 200), (60, 200), "lower"),
        ((44, 200), (40, 200), "no_clear_difference"),
    ],
)
def test_verdicts_need_minimum_samples_and_an_interval_excluding_zero(treated, baseline, verdict):
    assert compare_rates(treated, baseline, min_sample=30).verdict == verdict
