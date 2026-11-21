"""Root JobAgent command-line application."""

import sys

import typer

from jobagent.cli.feishu import feishu_app
from jobagent.cli.harness import harness_app

app = typer.Typer(
    name="jobagent",
    help="CareerHarness helpers: shared Bitable access and CV PDF rendering.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Emit UTF-8 JSON regardless of the console's default encoding."""
    # Resume and JD text is routinely non-ASCII; a legacy console codec such as
    # cp936 would otherwise raise UnicodeEncodeError while writing valid output.
    for stream in (sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", None) or ""
        if encoding.lower().replace("-", "") != "utf8":
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(encoding="utf-8", errors="backslashreplace")


app.add_typer(feishu_app, name="feishu")
app.add_typer(harness_app, name="harness")

if __name__ == "__main__":
    app()
