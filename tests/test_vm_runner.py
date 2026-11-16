"""Tests for deploy/vm/run_research_round.sh.

The runner is exercised with a fake `claude` executable, so no Claude session
and no BRAIN request is ever made: the only project command it runs is
`python -m app settings`, which builds no client.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "deploy" / "vm" / "run_research_round.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="the VM runner is a POSIX shell script",
)

LIVE_ENV = {
    "WQ_DRY_RUN": "false",
    "WQ_CLIENT_MODE": "requests",
    "WQ_USERNAME": "placeholder-user",
    "WQ_PASSWORD": "placeholder-password",
}


def _fake_claude(tmp_path: Path, exit_code: int = 0) -> Path:
    """A stand-in for `claude` that records its argv as JSON and exits."""
    record = tmp_path / "claude_argv.json"
    script = tmp_path / "fake-claude"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        f"open({str(record)!r}, 'w', encoding='utf-8').write(json.dumps(sys.argv[1:]))\n"
        "print('{\"result\": \"ok\"}')\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _run(tmp_path: Path, claude: Path, extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith(("WQ_", "CLAUDE_"))}
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "WQ_RUNNER_ENV_FILE": str(tmp_path / "no-such-env-file"),
            "WQ_RUNNER_PYTHON": sys.executable,
            "WQ_RUNNER_CLAUDE": str(claude),
            "WQ_RUNNER_STATE_DIR": str(tmp_path / "state"),
            # Keep the round's own paths away from the real research data.
            "WQ_RESEARCH_DIR": str(tmp_path / "research"),
            "WQ_OUTPUT_DIR": str(tmp_path / "outputs"),
            "WQ_CANDIDATE_FILE": str(tmp_path / "candidates.jsonl"),
            "WQ_LOG_DIR": str(tmp_path / "logs"),
        }
    )
    env.update(extra_env)
    return subprocess.run(
        ["bash", str(RUNNER)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _claude_argv(tmp_path: Path) -> list[str] | None:
    record = tmp_path / "claude_argv.json"
    if not record.exists():
        return None
    return json.loads(record.read_text(encoding="utf-8"))


def test_runner_refuses_a_dry_run_setup(tmp_path: Path) -> None:
    claude = _fake_claude(tmp_path)

    result = _run(tmp_path, claude, {**LIVE_ENV, "WQ_DRY_RUN": "true"})

    assert result.returncode == 3
    assert "refuse: settings does not show dry_run=False" in result.stderr
    assert _claude_argv(tmp_path) is None


def test_runner_refuses_when_credentials_are_missing(tmp_path: Path) -> None:
    claude = _fake_claude(tmp_path)

    result = _run(tmp_path, claude, {**LIVE_ENV, "WQ_PASSWORD": ""})

    assert result.returncode == 3
    assert "has_password=True" in result.stderr
    assert _claude_argv(tmp_path) is None


def test_runner_starts_one_restricted_headless_round(tmp_path: Path) -> None:
    claude = _fake_claude(tmp_path)

    result = _run(tmp_path, claude, {**LIVE_ENV, "WQ_RUNNER_MODE": "pass-alpha-improvement"})

    assert result.returncode == 0, result.stderr
    argv = _claude_argv(tmp_path)
    assert argv is not None
    assert argv[:2] == ["-p", "/worldquant-researcher-workflow pass-alpha-improvement"]
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--disallowedTools") + 1] == "Read(./.env)"
    allowed = argv[argv.index("--allowedTools") + 1 :]
    assert allowed == [
        f"Bash({sys.executable} -m app *)",
        "Read",
        "Glob",
        "Grep",
        "Edit(./data/candidates.jsonl)",
        "Edit(./research/notes/**)",
    ]
    assert "bypassPermissions" not in argv
    assert "--dangerously-skip-permissions" not in argv

    state = tmp_path / "state"
    rounds = sorted(state.glob("round-*.json"))
    assert len(rounds) == 1
    assert json.loads(rounds[0].read_text(encoding="utf-8")) == {"result": "ok"}
    assert not (state / "STOP").exists()
    assert not (state / "consecutive_failures").exists()


def test_runner_without_a_mode_passes_the_bare_skill_name(tmp_path: Path) -> None:
    claude = _fake_claude(tmp_path)

    result = _run(tmp_path, claude, LIVE_ENV)

    assert result.returncode == 0, result.stderr
    argv = _claude_argv(tmp_path)
    assert argv is not None
    assert argv[:2] == ["-p", "/worldquant-researcher-workflow"]
    assert "--model" not in argv


def test_stop_file_skips_the_round(tmp_path: Path) -> None:
    claude = _fake_claude(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    (state / "STOP").write_text("paused by the user\n", encoding="utf-8")

    result = _run(tmp_path, claude, LIVE_ENV)

    assert result.returncode == 0
    assert "skip:" in result.stderr
    assert _claude_argv(tmp_path) is None


def test_consecutive_failures_write_the_stop_file(tmp_path: Path) -> None:
    claude = _fake_claude(tmp_path, exit_code=1)
    state = tmp_path / "state"
    env = {**LIVE_ENV, "WQ_RUNNER_MAX_FAILURES": "2"}

    first = _run(tmp_path, claude, env)
    assert first.returncode == 1
    assert (state / "consecutive_failures").read_text(encoding="utf-8").strip() == "1"
    assert not (state / "STOP").exists()

    second = _run(tmp_path, claude, env)
    assert second.returncode == 1
    assert (state / "STOP").exists()

    (tmp_path / "claude_argv.json").unlink()
    third = _run(tmp_path, claude, env)
    assert third.returncode == 0
    assert _claude_argv(tmp_path) is None


def test_a_successful_round_resets_the_failure_count(tmp_path: Path) -> None:
    state = tmp_path / "state"
    env = {**LIVE_ENV, "WQ_RUNNER_MAX_FAILURES": "5"}

    assert _run(tmp_path, _fake_claude(tmp_path, exit_code=1), env).returncode == 1
    assert (state / "consecutive_failures").exists()

    assert _run(tmp_path, _fake_claude(tmp_path, exit_code=0), env).returncode == 0
    assert not (state / "consecutive_failures").exists()
