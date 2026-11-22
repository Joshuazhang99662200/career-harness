"""Resolve private platform preferences against verified host-local capabilities."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

Platform = Literal["boss", "liepin", "zhaopin", "linkedin", "ats", "xiaohongshu"]
Kind = Literal["browser_gui", "chrome_plugin", "mcp", "cli", "cloud_browser"]
Mode = Literal["interactive", "scheduled"]

GUI = frozenset({"browser_gui", "chrome_plugin", "cloud_browser"})
PRIORITY: dict[Mode, tuple[Kind, ...]] = {
    "interactive": ("browser_gui", "chrome_plugin", "mcp", "cli", "cloud_browser"),
    "scheduled": ("mcp", "cli", "cloud_browser", "browser_gui", "chrome_plugin"),
}


class PlatformSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routing_mode: Literal["auto", "override"] = "auto"
    selected: list[Platform] | None = None
    overrides: dict[Platform, Kind] = Field(default_factory=dict)
    prohibited: dict[Platform, list[Kind]] = Field(default_factory=dict)
    per_platform_quota: dict[Platform, int] = Field(default_factory=dict)
    total_quota: int | None = None
    schedule: str | None = None
    hard_filters: dict[str, JsonValue] | None = None


class Probe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Platform
    kind: Kind
    endpoint: str = Field(min_length=1)
    host: str = Field(min_length=1)
    session: str = Field(min_length=1)
    available: bool = False
    login: Literal["ready", "required", "unknown"] = "unknown"
    search_authorized: bool = False
    list_verified: bool = False
    jd_verified: bool = False
    page_verified: bool = False
    background_verified: bool = False
    scheduled_authorized: bool = False
    execution_verified: bool = False
    restricted: bool = False


class Route(BaseModel):
    status: str
    kind: Kind | None = None
    endpoint: str | None = None
    search_strategy: Literal["rank_candidates", "query_then_rank"] | None = None
    execution_verified: bool = False
    business_settings_pending: bool = False


class PlatformRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settings: PlatformSettings
    probes: list[Probe]
    host: str = Field(min_length=1)
    session: str = Field(min_length=1)
    mode: Mode


def route_platforms(
    settings: PlatformSettings, probes: list[Probe], *, host: str, session: str, mode: Mode,
) -> dict[Platform, Route]:
    return {
        platform: _route_platform(settings, platform, probes, host, session, mode)
        for platform in dict.fromkeys(settings.selected or [])
    }


def _route_platform(
    settings: PlatformSettings, platform: Platform, probes: list[Probe],
    host: str, session: str, mode: Mode,
) -> Route:
    same_platform = [probe for probe in probes if probe.platform == platform]
    same_host = [probe for probe in same_platform if probe.host == host]
    current = [probe for probe in same_host if probe.session == session]
    if any(probe.restricted for probe in current):
        return Route(status="restricted")
    override = settings.overrides.get(platform) if settings.routing_mode == "override" else None
    allowed = [kind for kind in PRIORITY[mode] if kind not in settings.prohibited.get(platform, [])
               and (override is None or kind == override)]
    if not allowed:
        return Route(status="forbidden")
    candidates = [probe for probe in current if probe.kind in allowed and probe.available]
    pending = not settings.per_platform_quota.get(platform) or settings.hard_filters is None
    if mode == "scheduled":
        pending = pending or not settings.schedule
    eligible = []
    blockers = []
    for probe in candidates:
        blocker = _blocker(probe, mode)
        if blocker:
            blockers.append(blocker)
        else:
            eligible.append(probe)
    if eligible:
        winner = min(eligible, key=lambda probe: (allowed.index(probe.kind), probe.endpoint))
        return Route(
            status="business_settings_pending" if pending and mode == "scheduled" else "ready",
            kind=winner.kind, endpoint=winner.endpoint,
            search_strategy="rank_candidates" if winner.kind in GUI else "query_then_rank",
            execution_verified=winner.execution_verified, business_settings_pending=pending,
        )
    if blockers:
        return Route(status=blockers[0])
    if same_host and not current:
        return Route(status="needs_probe")
    return Route(status="override_unavailable" if override else "unsupported")


def _blocker(probe: Probe, mode: Mode) -> str | None:
    if probe.login == "required":
        return "needs_login"
    if probe.login != "ready":
        return "needs_probe"
    if not probe.search_authorized:
        return "needs_authorization"
    if not (probe.list_verified and probe.jd_verified and probe.page_verified):
        return "unverified"
    if mode == "scheduled" and not (probe.background_verified and probe.scheduled_authorized):
        return "no_background_route"
    return None
