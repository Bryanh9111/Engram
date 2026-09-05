"""Regression tests for the opt-in Claude Code hooks."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from engram.model import MemoryKind
from engram.store import MemoryStore

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "hooks" / "user_prompt_submit.sh"
MEMORY_SUMMARY = "Zebrafish quorum sensor calibration fixture"

pytestmark = pytest.mark.skipif(
    shutil.which("uv") is None,
    reason="uv is required to run the hook",
)


@pytest.fixture
def run_hook(tmp_path):
    db_path = tmp_path / "hook.db"
    store = MemoryStore(str(db_path))
    store.remember(
        content="Calibration uses the zebrafish-quorum-sensor memory token.",
        summary=MEMORY_SUMMARY,
        kind=MemoryKind.FACT,
        project="hooktest",
    )
    store.close()

    env = {
        **os.environ,
        "ENGRAM_DB": str(db_path),
        "ENGRAM_WHISPER": "1",
        "PATH": os.environ.get("PATH", ""),
    }

    def _run(
        stdin: str,
        *,
        path: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        run_env = {**env}
        if path is not None:
            run_env["PATH"] = path
        return subprocess.run(
            ["bash", str(HOOK)],
            cwd=REPO_ROOT,
            env=run_env,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    return _run


def test_user_prompt_submit_extracts_prompt_from_json(run_hook):
    payload = json.dumps(
        {
            "session_id": "junk-session-" + "x" * 800,
            "transcript_path": "/tmp/" + "junk/" * 200 + "transcript.jsonl",
            "cwd": "/tmp/" + "irrelevant/" * 200,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "explain zebrafish-quorum-sensor calibration",
        }
    )

    result = run_hook(payload)

    assert result.returncode == 0
    assert "<engram_whisper>" in result.stdout
    assert MEMORY_SUMMARY in result.stdout


def test_user_prompt_submit_stays_silent_when_json_prompt_has_no_match(run_hook):
    payload = json.dumps({"prompt": "completely unrelated qwertyuiop"})

    result = run_hook(payload)

    assert result.returncode == 0
    assert "<engram_whisper>" not in result.stdout


def test_user_prompt_submit_accepts_plain_text_fallback(run_hook):
    result = run_hook("zebrafish-quorum-sensor plain text fallback")

    assert result.returncode == 0
    assert "<engram_whisper>" in result.stdout
    assert MEMORY_SUMMARY in result.stdout


def test_user_prompt_submit_stays_silent_when_json_has_no_prompt(run_hook):
    payload = json.dumps(
        {
            "session_id": "x",
            "transcript_path": "/tmp/transcript.jsonl",
            "cwd": "/tmp",
            "hook_event_name": "UserPromptSubmit",
        }
    )

    result = run_hook(payload)

    assert result.returncode == 0
    assert result.stdout == ""


def test_user_prompt_submit_uses_python_when_jq_is_unavailable(
    run_hook,
    tmp_path,
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for command in ("bash", "cat", "cut", "dirname", "python3", "tr", "uv"):
        executable = shutil.which(command)
        assert executable is not None
        (bin_dir / command).symlink_to(executable)

    payload = json.dumps(
        {"prompt": "explain zebrafish-quorum-sensor calibration"}
    )
    result = run_hook(payload, path=str(bin_dir))

    assert result.returncode == 0
    assert "<engram_whisper>" in result.stdout
    assert MEMORY_SUMMARY in result.stdout
