from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "dev"


def run_dev(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "VIBE_DEV_STATE_DIR": str(tmp_path / "state"),
        "VIBE_BACKEND_PORT": "49191",
        "VIBE_FRONTEND_PORT": "49192",
    }
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )


def test_doctor_reports_actionable_failures_when_services_are_stopped(tmp_path):
    result = run_dev(tmp_path, "doctor")

    assert result.returncode == 1
    assert "unknown command" not in result.stderr
    assert "FAIL backend health" in result.stdout
    assert "FAIL frontend page" in result.stdout
    assert "FAIL frontend proxy" in result.stdout
    assert "scripts/dev up" in result.stdout


def test_status_removes_stale_pid_files(tmp_path):
    pid_dir = tmp_path / "state" / "pids"
    pid_dir.mkdir(parents=True)
    stale = pid_dir / "backend.pid"
    stale.write_text("999999", encoding="utf-8")

    result = run_dev(tmp_path, "status")

    assert result.returncode == 0
    assert not stale.exists()
    assert "backend  stopped" in result.stdout
