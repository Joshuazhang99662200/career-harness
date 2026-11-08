import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_muse_transport_generated_from_authoritative_schemas():
    result = subprocess.run(
        [sys.executable, "scripts/build_muse_contracts.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_muse_reference_layout_is_preserved_and_personal_migrations_are_absent():
    source = (ROOT / "frontend/src/muse/MuseSpaceApp.tsx").read_text(encoding="utf-8")
    for name in [
        "FiveColumnTable",
        "TodoDialog",
        "JobDetailDialog",
        "ExecConfirmView",
        "EchoPanel",
        "MaterialList",
        "RunsPanel",
        "CommsPanel",
        "AboutPanel",
    ]:
        assert f"function {name}(" in source
    assert "需要你决定" not in source
    assert "Signal / Harness" not in source
    assert 'j.job["host_rank"]) >= 160' not in source
    assert "@hatch/space-sdk" not in source
    assert "./console/console.js" not in source


def test_the_shared_theme_keeps_the_recorded_source_fingerprint():
    directory = ROOT / "frontend/src/muse"
    provenance = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
    # The zip reference copy and the earlier share-page template are retired.
    assert not (directory / "MuseApp.tsx").exists()
    assert not (directory / "MuseCurrentApp.tsx").exists()
    assert (
        hashlib.sha256((directory / "theme.css").read_bytes()).hexdigest()
        == provenance["zip_theme_sha256"]
    )
