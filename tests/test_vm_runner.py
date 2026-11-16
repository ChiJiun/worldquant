"""Tests for deploy/vm/run_research_round.sh.

The runner is exercised with a fake `claude` executable that behaves like the
real one where it matters here: it reads the hook from `--settings` and calls it
before each pretended tool call. No Claude session is started and no request
reaches BRAIN: the runner's only project command is `python -m app settings`
(which constructs a client object but sends nothing), and the credentials are
placeholders set by the test.
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

FAKE_CLAUDE = r'''
import json, os, subprocess, sys, time

argv = sys.argv[1:]
record = os.environ["FAKE_CLAUDE_RECORD"]
with open(record, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(argv) + "\n")

if argv[:1] == ["--version"]:
    print("9.9.9 (Fake Claude)")
    sys.exit(0)

prompt = argv[argv.index("-p") + 1]
settings = json.loads(argv[argv.index("--settings") + 1])
hook = settings["hooks"]["PreToolUse"][0]["hooks"][0]
repo = os.environ["WQ_GUARD_REPO"]
python = os.environ["WQ_GUARD_PYTHON"]


def tool_call(tool, tool_input):
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": repo}
    done = subprocess.run([hook["command"], *hook["args"]], input=json.dumps(payload), text=True, capture_output=True)
    with open(record + ".hooks", "a", encoding="utf-8") as handle:
        handle.write("%s %d\n" % (tool, done.returncode))


selftest = prompt.startswith("Tool permission self-test")
mode = os.environ.get("FAKE_CLAUDE_SELFTEST" if selftest else "FAKE_CLAUDE_ROUND", "ok")
time.sleep(float(os.environ.get("FAKE_CLAUDE_SLEEP", "0")))

if mode == "crash":
    sys.stderr.write("not logged in\n")
    sys.exit(1)
if selftest and mode == "ok":
    tool_call("Bash", {"command": "echo wq-guard-probe"})
    tool_call("Read", {"file_path": "/etc/hostname"})
elif mode in ("ok", "exit1", "error-json"):
    tool_call("Read", {"file_path": "README.md"})
elif mode == "simulate-twice":
    for _ in range(2):
        tool_call("Bash", {"command": python + " -m app simulate --limit 1 --current-run"})
# mode "no-hook": pretend the hook is not wired and call nothing

result = {"result": "ok", "subtype": "success", "is_error": False, "num_turns": 3}
if mode == "error-json":
    result.update({"subtype": "error_max_turns", "is_error": True})
print(json.dumps(result))
sys.exit(1 if mode == "exit1" else 0)
'''


class Sandbox:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.state = tmp_path / "state"
        self.record = tmp_path / "claude_calls.jsonl"
        self.claude = tmp_path / "fake-claude"
        self.claude.write_text(f"#!{sys.executable}\n{FAKE_CLAUDE}", encoding="utf-8")
        self.claude.chmod(self.claude.stat().st_mode | stat.S_IXUSR)

    def run(self, **extra_env: str) -> subprocess.CompletedProcess[str]:
        env = {key: value for key, value in os.environ.items() if not key.startswith(("WQ_", "CLAUDE_", "FAKE_CLAUDE_"))}
        env.update(LIVE_ENV)
        env.update(
            {
                "HOME": str(self.tmp / "home"),
                "FAKE_CLAUDE_RECORD": str(self.record),
                "WQ_RUNNER_ENV_FILE": str(self.tmp / "no-such-env-file"),
                "WQ_RUNNER_PYTHON": sys.executable,
                "WQ_RUNNER_CLAUDE": str(self.claude),
                "WQ_RUNNER_STATE_DIR": str(self.state),
                # Keep the app's own paths away from the real research data.
                "WQ_RESEARCH_DIR": str(self.tmp / "research"),
                "WQ_OUTPUT_DIR": str(self.tmp / "outputs"),
                "WQ_CANDIDATE_FILE": str(self.tmp / "candidates.jsonl"),
                "WQ_LOG_DIR": str(self.tmp / "logs"),
            }
        )
        env.update(extra_env)
        return subprocess.run(["bash", str(RUNNER)], env=env, capture_output=True, text=True, timeout=180, check=False)

    def calls(self) -> list[list[str]]:
        if not self.record.exists():
            return []
        return [json.loads(line) for line in self.record.read_text(encoding="utf-8").splitlines()]

    def prompts(self) -> list[str]:
        return [call[call.index("-p") + 1] for call in self.calls() if "-p" in call]

    def hook_results(self) -> list[str]:
        path = Path(str(self.record) + ".hooks")
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def failures(self) -> str | None:
        path = self.state / "consecutive_failures"
        return path.read_text(encoding="utf-8").strip() if path.exists() else None

    def stop_text(self) -> str | None:
        path = self.state / "STOP"
        return path.read_text(encoding="utf-8") if path.exists() else None


@pytest.fixture()
def sandbox(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


def test_runner_refuses_a_dry_run_setup(sandbox: Sandbox) -> None:
    result = sandbox.run(WQ_DRY_RUN="true")

    assert result.returncode == 3
    assert "refuse: settings does not show dry_run=False" in result.stderr
    assert sandbox.calls() == []


def test_runner_refuses_a_mock_client(sandbox: Sandbox) -> None:
    result = sandbox.run(WQ_CLIENT_MODE="mock")

    assert result.returncode == 3
    assert "client_mode=requests" in result.stderr
    assert sandbox.calls() == []


def test_runner_refuses_when_credentials_are_missing(sandbox: Sandbox) -> None:
    result = sandbox.run(WQ_PASSWORD="")

    assert result.returncode == 3
    assert "has_password=True" in result.stderr
    assert sandbox.calls() == []


def test_first_run_self_tests_the_guard_then_runs_one_restricted_round(sandbox: Sandbox) -> None:
    result = sandbox.run(WQ_RUNNER_MODE="pass-alpha-improvement")

    assert result.returncode == 0, result.stderr
    prompts = sandbox.prompts()
    assert len(prompts) == 2
    assert prompts[0].startswith("Tool permission self-test")
    assert prompts[1] == "/worldquant-researcher-workflow pass-alpha-improvement"
    # Both probes were blocked by the real guard, the round's read was let through.
    assert sandbox.hook_results() == ["Bash 2", "Read 2", "Read 0"]
    assert "selftest: ok" in result.stderr

    argv = sandbox.calls()[-1]
    assert argv[0] == "-p"
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--max-turns") + 1] == "80"
    assert argv[argv.index("--output-format") + 1] == "json"
    assert "--model" not in argv
    assert "bypassPermissions" not in argv
    assert "--dangerously-skip-permissions" not in argv
    denied = argv[argv.index("--disallowedTools") + 1 : argv.index("--allowedTools")]
    assert denied == ["Read(./.env)", "WebFetch", "WebSearch", "Agent"]
    assert argv[argv.index("--allowedTools") + 1 :] == [
        f"Bash({sys.executable} -m app *)",
        "Edit(./data/candidates.jsonl)",
        "Edit(./research/notes/**/*.md)",
    ]

    settings = json.loads(argv[argv.index("--settings") + 1])
    assert settings["permissions"] == {
        "blockReadsOutsideWorkingDirectories": True,
        "blockWritesOutsideWorkingDirectories": True,
    }
    (group,) = settings["hooks"]["PreToolUse"]
    assert group["matcher"] == "*"
    (hook,) = group["hooks"]
    assert hook["type"] == "command"
    assert hook["command"] == sys.executable
    assert hook["args"] == [str(REPO_ROOT / "deploy" / "vm" / "tool_guard.py")]
    assert hook["onFailure"] == "block"

    rules = argv[argv.index("--append-system-prompt") + 1]
    assert "unattended" in rules and "--limit 1" in rules and "Never submit" in rules

    rounds = sorted(sandbox.state.glob("round-*.json"))
    assert len(rounds) == 1
    assert json.loads(rounds[0].read_text(encoding="utf-8"))["subtype"] == "success"
    assert list(sandbox.state.glob("guard-verified-*"))
    assert sandbox.stop_text() is None
    assert sandbox.failures() is None
    assert "done: round" in result.stderr and "guard_calls=1" in result.stderr and "simulate=no" in result.stderr


def test_self_test_runs_once_per_claude_version(sandbox: Sandbox) -> None:
    assert sandbox.run().returncode == 0
    assert sandbox.run(WQ_RUNNER_MODEL="sonnet").returncode == 0

    prompts = sandbox.prompts()
    assert [prompt.startswith("Tool permission self-test") for prompt in prompts] == [True, False, False]
    assert prompts[-1] == "/worldquant-researcher-workflow"
    last = sandbox.calls()[-1]
    assert last[last.index("--model") + 1] == "sonnet"


def test_unwired_hook_fails_the_self_test_and_stops_the_loop(sandbox: Sandbox) -> None:
    result = sandbox.run(FAKE_CLAUDE_SELFTEST="no-hook")

    assert result.returncode == 4
    assert len(sandbox.prompts()) == 1
    assert "self-test failed" in (sandbox.stop_text() or "")
    assert not list(sandbox.state.glob("guard-verified-*"))

    again = sandbox.run()
    assert again.returncode == 0
    assert "skip:" in again.stderr
    assert len(sandbox.prompts()) == 1


def test_claude_failing_before_any_tool_call_is_an_ordinary_failure(sandbox: Sandbox) -> None:
    result = sandbox.run(FAKE_CLAUDE_SELFTEST="crash")

    assert result.returncode == 1
    assert sandbox.failures() == "1"
    assert sandbox.stop_text() is None
    assert not list(sandbox.state.glob("guard-verified-*"))
    assert len(sandbox.prompts()) == 1


def test_round_without_any_guard_call_stops_the_loop(sandbox: Sandbox) -> None:
    result = sandbox.run(FAKE_CLAUDE_ROUND="no-hook")

    assert result.returncode == 4
    assert "without a single tool-guard call" in (sandbox.stop_text() or "")
    assert not list(sandbox.state.glob("guard-verified-*"))


def test_guard_lets_one_simulate_through_per_round(sandbox: Sandbox) -> None:
    result = sandbox.run(FAKE_CLAUDE_ROUND="simulate-twice")

    assert result.returncode == 0, result.stderr
    assert sandbox.hook_results()[-2:] == ["Bash 0", "Bash 2"]
    assert "simulate=yes" in result.stderr and "guard_denials=1" in result.stderr


def test_stop_file_skips_the_round(sandbox: Sandbox) -> None:
    sandbox.state.mkdir()
    (sandbox.state / "STOP").write_text("paused by the user\n", encoding="utf-8")

    result = sandbox.run()

    assert result.returncode == 0
    assert "skip:" in result.stderr
    assert sandbox.calls() == []


def test_consecutive_failures_write_the_stop_file(sandbox: Sandbox) -> None:
    env = {"FAKE_CLAUDE_ROUND": "exit1", "WQ_RUNNER_MAX_FAILURES": "2"}

    assert sandbox.run(**env).returncode == 1
    assert sandbox.failures() == "1"
    assert sandbox.stop_text() is None

    assert sandbox.run(**env).returncode == 1
    assert "consecutive failures" in (sandbox.stop_text() or "")

    before = len(sandbox.calls())
    assert sandbox.run(**env).returncode == 0
    assert len(sandbox.calls()) == before


def test_a_successful_round_resets_the_failure_count(sandbox: Sandbox) -> None:
    assert sandbox.run(FAKE_CLAUDE_ROUND="exit1", WQ_RUNNER_MAX_FAILURES="5").returncode == 1
    assert sandbox.failures() == "1"

    assert sandbox.run(WQ_RUNNER_MAX_FAILURES="5").returncode == 0
    assert sandbox.failures() is None


def test_an_error_result_counts_as_a_failure_even_with_exit_code_zero(sandbox: Sandbox) -> None:
    result = sandbox.run(FAKE_CLAUDE_ROUND="error-json")

    assert result.returncode == 1
    assert sandbox.failures() == "1"
    assert "subtype=error_max_turns" in result.stderr


def test_a_corrupt_failure_counter_is_treated_as_zero(sandbox: Sandbox) -> None:
    sandbox.state.mkdir()
    (sandbox.state / "consecutive_failures").write_text("x\n", encoding="utf-8")

    assert sandbox.run(FAKE_CLAUDE_ROUND="exit1").returncode == 1
    assert sandbox.failures() == "1"


@pytest.mark.parametrize("name", ["WQ_RUNNER_MAX_FAILURES", "WQ_RUNNER_MAX_TURNS", "WQ_RUNNER_KEEP_LOGS", "WQ_RUNNER_BASH_TIMEOUT_MS"])
@pytest.mark.parametrize("value", ["abc", "0", "-1", "1.5"])
def test_non_integer_limits_are_rejected_before_anything_runs(sandbox: Sandbox, name: str, value: str) -> None:
    result = sandbox.run(**{name: value})

    assert result.returncode == 2
    assert "must be a positive integer" in result.stderr
    assert sandbox.calls() == []


def test_round_timeout_is_a_failure(sandbox: Sandbox) -> None:
    assert sandbox.run().returncode == 0  # self-test done, marker written

    result = sandbox.run(WQ_RUNNER_TIMEOUT="1s", FAKE_CLAUDE_SLEEP="20")

    assert result.returncode == 124
    assert sandbox.failures() == "1"


def test_old_round_files_are_pruned(sandbox: Sandbox) -> None:
    sandbox.state.mkdir()
    for index in range(3):
        stem = sandbox.state / f"round-2000010{index}T000000Z"
        for suffix in (".json", ".json.err", ".guard.log", ".simulate"):
            Path(str(stem) + suffix).write_text("{}", encoding="utf-8")
        os.utime(Path(str(stem) + ".json"), (index + 1, index + 1))

    assert sandbox.run(WQ_RUNNER_KEEP_LOGS="1").returncode == 0

    remaining = sorted(path.name for path in sandbox.state.glob("round-*"))
    assert len([name for name in remaining if name.endswith(".json")]) == 1
    assert not [name for name in remaining if name.startswith("round-2000")]


def test_missing_claude_is_reported(sandbox: Sandbox) -> None:
    result = sandbox.run(WQ_RUNNER_CLAUDE=str(sandbox.tmp / "no-such-claude"))

    assert result.returncode == 2
    assert "not found on PATH" in result.stderr
