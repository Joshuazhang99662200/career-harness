"""Private inputs and machine-readable decisions for the Initial Setup skill."""

import json
from pathlib import Path
from typing import Annotated

import typer

from jobagent.cli.private_io import fail, read_model
from jobagent.errors import JobAgentError
from jobagent.setup.bootstrap import BootstrapSnapshot, plan_bootstrap, read_contract
from jobagent.setup.facts import FactDiscoveryRequest, plan_fact_discovery
from jobagent.setup.host_role import HostRoleRequest, resolve_host_role
from jobagent.setup.platforms import PlatformRequest, route_platforms

setup_app = typer.Typer(help="Plan Initial Setup using observed Feishu and host capabilities.")
RequestOption = Annotated[Path, typer.Option("--request")]


@setup_app.command("host-role")
def host_role(request: RequestOption) -> None:
    """Resolve the host label, role prompt and role-specific setup route."""
    try:
        typer.echo(resolve_host_role(read_model(request, HostRoleRequest)).model_dump_json())
    except JobAgentError as error:
        fail(error)


@setup_app.command("personal-facts")
def personal_facts(request: RequestOption) -> None:
    """Plan material reuse, drafting and the next GM coverage question."""
    try:
        typer.echo(plan_fact_discovery(read_model(request, FactDiscoveryRequest)).model_dump_json())
    except JobAgentError as error:
        fail(error)


@setup_app.command("feishu-plan")
def feishu_plan(request: RequestOption, contract: Annotated[Path, typer.Option()]) -> None:
    """Plan the next Feishu stage from a private official CLI snapshot."""
    try:
        result = plan_bootstrap(read_contract(contract), read_model(request, BootstrapSnapshot))
        typer.echo(result.model_dump_json())
    except JobAgentError as error:
        fail(error)


@setup_app.command("platform-routes")
def platform_routes(request: RequestOption) -> None:
    """Select a verified search route per platform for this host and mode."""
    try:
        observed = read_model(request, PlatformRequest)
        routes = route_platforms(observed.settings, observed.probes, host=observed.host,
                                 session=observed.session, mode=observed.mode)
        typer.echo(json.dumps({platform: route.model_dump() for platform, route in routes.items()}))
    except JobAgentError as error:
        fail(error)
